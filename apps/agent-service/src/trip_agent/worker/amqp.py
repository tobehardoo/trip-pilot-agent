"""AMQP transport for the planning worker."""

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any, Literal, Protocol, Self
from urllib.parse import quote
from uuid import UUID

import aio_pika
import httpx
import psycopg
from aio_pika.abc import AbstractExchange, AbstractIncomingMessage
from pydantic import Field, SecretStr, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from trip_agent.acquisition.registry import SourceCatalog
from trip_agent.providers.map import AmapMapProvider, JsonCache
from trip_agent.providers.redis_cache import RedisJsonCache
from trip_agent.providers.route import AmapRouteProvider
from trip_agent.retrieval.embeddings import (
    DashScopeEmbeddingProvider,
    EmbeddingProvider,
    HashEmbeddingProvider,
)
from trip_agent.retrieval.repository import PsycopgKnowledgeRepository
from trip_agent.worker.contracts import PlanningCancelCommand, PlanningCreateCommand
from trip_agent.worker.knowledge import (
    KnowledgeFreshnessProvider,
    KnowledgeSearchRepository,
    RetrievalKnowledgeEvidenceProvider,
    StaticCatalogKnowledgeFreshnessProvider,
)
from trip_agent.worker.processor import (
    AmapPlanningProvider,
    DemoKnowledgeEvidenceProvider,
    DemoPlanningProvider,
    FallbackPlanningProvider,
    KnowledgeEvidenceProvider,
    PlanningInfeasibleError,
    PlanningProvider,
    planning_failed_event,
    process_planning_create,
)

COMMAND_EXCHANGE = "trip.command.exchange"
EVENT_EXCHANGE = "trip.event.exchange"
DEAD_LETTER_EXCHANGE = "trip.dead-letter.exchange"
CREATE_QUEUE = "planning.create.queue"
CANCEL_QUEUE = "planning.cancel.queue"
DEAD_LETTER_QUEUE = "planning.dead-letter.queue"
CREATE_ROUTING_KEY = "planning.create"
CANCEL_ROUTING_KEY = "planning.cancel"
COMPLETED_ROUTING_KEY = "planning.completed"
FAILED_ROUTING_KEY = "planning.failed"
DEAD_LETTER_ROUTING_KEY = "planning.create.dead"
CANCEL_DEAD_LETTER_ROUTING_KEY = "planning.cancel.dead"

logger = logging.getLogger("trip_agent.worker")


class IncomingDelivery(Protocol):
    body: bytes

    def ack(self) -> Awaitable[None]: ...

    def reject(self, *, requeue: bool) -> Awaitable[None]: ...

    def nack(self, *, requeue: bool) -> Awaitable[None]: ...


class EventExchange(Protocol):
    def publish(
        self,
        message: aio_pika.Message,
        *,
        routing_key: str,
        mandatory: bool,
    ) -> Awaitable[Any]: ...


class CancellationOracle(Protocol):
    def is_cancelled(self, task_id: UUID) -> Awaitable[bool]: ...


class PsycopgCancellationOracle:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    async def is_cancelled(self, task_id: UUID) -> bool:
        async with (
            await psycopg.AsyncConnection.connect(self._database_url) as connection,
            connection.cursor() as cursor,
        ):
            await cursor.execute(
                "SELECT status FROM business.planning_task WHERE id = %s",
                (task_id,),
            )
            row = await cursor.fetchone()
        return row is not None and row[0] == "CANCELLED"


class CancellationRegistry:
    """Process-local cooperative cancellation signals keyed by planning task."""

    def __init__(self) -> None:
        self._cancelled: set[UUID] = set()
        self._events: dict[UUID, asyncio.Event] = {}

    def signal_for(self, task_id: UUID) -> asyncio.Event:
        event = self._events.setdefault(task_id, asyncio.Event())
        if task_id in self._cancelled:
            event.set()
        return event

    def cancel(self, task_id: UUID) -> None:
        self._cancelled.add(task_id)
        event = self._events.get(task_id)
        if event is not None:
            event.set()

    def finish(self, task_id: UUID) -> None:
        self._events.pop(task_id, None)


async def _is_cancelled(
    task_id: UUID,
    registry: CancellationRegistry | None,
    oracle: CancellationOracle | None,
) -> bool:
    if registry is not None and registry.signal_for(task_id).is_set():
        return True
    return oracle is not None and await oracle.is_cancelled(task_id)


class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="",
        env_file=(".env", "../../.env"),
        extra="ignore",
        frozen=True,
    )

    rabbitmq_host: str = "localhost"
    rabbitmq_port: int = 5672
    rabbitmq_user: str = "trip_pilot"
    rabbitmq_password: str = "replace-with-local-password"
    demo_mode: bool = True
    amap_web_service_key: SecretStr | None = None
    amap_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    poi_cache_ttl_seconds: int = Field(default=86_400, gt=0)
    route_cache_ttl_seconds: int = Field(default=3_600, gt=0)
    redis_host: str = "localhost"
    redis_port: int = Field(default=6379, ge=1, le=65_535)
    redis_password: SecretStr = SecretStr("replace-with-local-password")
    redis_db: int = Field(default=0, ge=0)
    redis_timeout_seconds: float = Field(default=2.0, gt=0, le=30)
    knowledge_database_url: SecretStr | None = None
    knowledge_embedding_provider: Literal["demo", "dashscope"] = "demo"
    knowledge_embedding_dimensions: int = Field(default=1024, ge=1, le=4096)
    knowledge_embedding_model: str = "text-embedding-v4"
    dashscope_api_key: SecretStr | None = None
    dashscope_embedding_base_url: str = (
        "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
    dashscope_embedding_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    knowledge_source_directory: Path = Path("../../knowledge/sources")
    postgres_host: str = "localhost"
    postgres_port: int = Field(default=5432, ge=1, le=65_535)
    postgres_db: str = "trip_pilot"
    postgres_user: str = "trip_pilot"
    postgres_password: SecretStr = SecretStr("local-development-only")

    @model_validator(mode="after")
    def require_real_provider_key(self) -> Self:
        key = self.amap_web_service_key
        if not self.demo_mode and (key is None or not key.get_secret_value().strip()):
            raise ValueError("AMAP_WEB_SERVICE_KEY is required when DEMO_MODE=false")
        embedding_key = self.dashscope_api_key
        if (
            not self.demo_mode
            and self.knowledge_embedding_provider == "dashscope"
            and (embedding_key is None or not embedding_key.get_secret_value().strip())
        ):
            raise ValueError("DASHSCOPE_API_KEY is required for DashScope embeddings")
        return self

    def redis_connection_url(self) -> str:
        password = quote(self.redis_password.get_secret_value(), safe="")
        return f"redis://:{password}@{self.redis_host}:{self.redis_port}/{self.redis_db}"

    def knowledge_connection_url(self) -> str:
        if self.knowledge_database_url is not None:
            configured = self.knowledge_database_url.get_secret_value().strip()
            if configured:
                return configured
        return self.business_connection_url()

    def business_connection_url(self) -> str:
        password = quote(self.postgres_password.get_secret_value(), safe="")
        return (
            f"postgresql://{quote(self.postgres_user, safe='')}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}/{quote(self.postgres_db, safe='')}"
        )


@dataclass(frozen=True, slots=True)
class WorkerRuntime:
    planning_provider: PlanningProvider
    knowledge_provider: KnowledgeEvidenceProvider
    cancellation_oracle: CancellationOracle


def build_planning_provider(
    settings: WorkerSettings,
    *,
    http_client: httpx.AsyncClient | None = None,
    cache: JsonCache | None = None,
) -> PlanningProvider:
    if settings.demo_mode:
        return DemoPlanningProvider()
    if http_client is None:
        raise ValueError("HTTP client is required in real provider mode")
    key = settings.amap_web_service_key
    if key is None:
        raise ValueError("AMap key is required in real provider mode")
    amap_map = AmapMapProvider(
        api_key=key.get_secret_value(),
        http_client=http_client,
        cache=cache,
        cache_ttl_seconds=settings.poi_cache_ttl_seconds,
    )
    amap_route = AmapRouteProvider(
        api_key=key.get_secret_value(),
        http_client=http_client,
        cache=cache,
        cache_ttl_seconds=settings.route_cache_ttl_seconds,
    )
    return FallbackPlanningProvider(
        AmapPlanningProvider(amap_map, amap_route),
        DemoPlanningProvider(),
    )


def build_knowledge_provider(
    settings: WorkerSettings,
    *,
    embedding_provider: EmbeddingProvider | None = None,
    repository: KnowledgeSearchRepository | None = None,
    freshness_provider: KnowledgeFreshnessProvider | None = None,
) -> KnowledgeEvidenceProvider:
    if settings.demo_mode:
        return DemoKnowledgeEvidenceProvider()
    database_url = settings.knowledge_connection_url()
    selected_embedding = embedding_provider or _configured_embedding_provider(settings)
    selected_repository = repository or PsycopgKnowledgeRepository(database_url)
    if freshness_provider is None:
        freshness_provider = StaticCatalogKnowledgeFreshnessProvider(
            catalog=SourceCatalog.load_directory(settings.knowledge_source_directory),
        )
    return RetrievalKnowledgeEvidenceProvider(
        embedding_provider=selected_embedding,
        repository=selected_repository,
        freshness_provider=freshness_provider,
    )


def _configured_embedding_provider(settings: WorkerSettings) -> EmbeddingProvider:
    if settings.knowledge_embedding_provider == "demo":
        return HashEmbeddingProvider(dimensions=settings.knowledge_embedding_dimensions)
    key = settings.dashscope_api_key
    if key is None:
        raise ValueError("DASHSCOPE_API_KEY is required for DashScope embeddings")
    return DashScopeEmbeddingProvider(
        api_key=key.get_secret_value(),
        base_url=settings.dashscope_embedding_base_url,
        model_name=settings.knowledge_embedding_model,
        dimensions=settings.knowledge_embedding_dimensions,
        timeout_seconds=settings.dashscope_embedding_timeout_seconds,
    )


@asynccontextmanager
async def planning_provider_runtime(
    settings: WorkerSettings,
) -> AsyncIterator[PlanningProvider]:
    if settings.demo_mode:
        yield DemoPlanningProvider()
        return
    async with httpx.AsyncClient(timeout=settings.amap_timeout_seconds) as http_client:
        cache = RedisJsonCache.from_url(
            settings.redis_connection_url(),
            socket_connect_timeout=settings.redis_timeout_seconds,
            socket_timeout=settings.redis_timeout_seconds,
        )
        try:
            yield build_planning_provider(
                settings,
                http_client=http_client,
                cache=cache,
            )
        finally:
            await cache.aclose()


@asynccontextmanager
async def worker_runtime(settings: WorkerSettings) -> AsyncIterator[WorkerRuntime]:
    async with planning_provider_runtime(settings) as planning_provider:
        yield WorkerRuntime(
            planning_provider=planning_provider,
            knowledge_provider=build_knowledge_provider(settings),
            cancellation_oracle=PsycopgCancellationOracle(
                settings.business_connection_url()
            ),
        )


async def handle_delivery(
    message: IncomingDelivery,
    event_exchange: EventExchange,
    provider: PlanningProvider | None = None,
    knowledge_provider: KnowledgeEvidenceProvider | None = None,
    cancellation_registry: CancellationRegistry | None = None,
    cancellation_oracle: CancellationOracle | None = None,
) -> None:
    try:
        command = PlanningCreateCommand.model_validate_json(message.body)
    except (ValidationError, TypeError, ValueError) as exception:
        error_count = exception.error_count() if isinstance(exception, ValidationError) else 1
        logger.warning("rejecting invalid planning command: %s", error_count)
        await message.reject(requeue=False)
        return

    try:
        process_task = asyncio.create_task(process_planning_create(
            command,
            provider or DemoPlanningProvider(),
            knowledge_provider=knowledge_provider,
        ))
        cancel_wait: asyncio.Task[bool] | None = None
        if cancellation_registry is not None:
            signal = cancellation_registry.signal_for(command.task_id)
            if signal.is_set():
                process_task.cancel()
                with suppress(asyncio.CancelledError):
                    await process_task
                cancellation_registry.finish(command.task_id)
                await message.ack()
                return
            cancel_wait = asyncio.create_task(signal.wait())
            done, _ = await asyncio.wait(
                (process_task, cancel_wait),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if cancel_wait in done and signal.is_set():
                process_task.cancel()
                with suppress(asyncio.CancelledError):
                    await process_task
                cancellation_registry.finish(command.task_id)
                await message.ack()
                return
            cancel_wait.cancel()
            with suppress(asyncio.CancelledError):
                await cancel_wait
        completed = await process_task
        if await _is_cancelled(command.task_id, cancellation_registry, cancellation_oracle):
            if cancellation_registry is not None:
                cancellation_registry.finish(command.task_id)
            await message.ack()
            return
        outgoing = aio_pika.Message(
            body=completed.model_dump_json(by_alias=True, exclude_none=True).encode(),
            content_type="application/json",
            content_encoding="utf-8",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            message_id=str(completed.event_id),
            correlation_id=str(completed.trace_id),
            type=completed.event_type,
            headers={
                "traceId": str(completed.trace_id),
                "taskId": str(completed.task_id),
                "tripId": str(completed.trip_id),
                "runId": str(completed.run_id),
            },
        )
        await event_exchange.publish(
            outgoing,
            routing_key=COMPLETED_ROUTING_KEY,
            mandatory=True,
        )
    except PlanningInfeasibleError as failure:
        try:
            cancelled = await _is_cancelled(
                command.task_id,
                cancellation_registry,
                cancellation_oracle,
            )
        except Exception:
            logger.exception("could not verify task status before failure publication")
            if cancellation_registry is not None:
                cancellation_registry.finish(command.task_id)
            await message.nack(requeue=True)
            return
        if cancelled:
            if cancellation_registry is not None:
                cancellation_registry.finish(command.task_id)
            await message.ack()
            return
        failed = planning_failed_event(command, failure)
        outgoing = aio_pika.Message(
            body=failed.model_dump_json(by_alias=True, exclude_none=True).encode(),
            content_type="application/json",
            content_encoding="utf-8",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            message_id=str(failed.event_id),
            correlation_id=str(failed.trace_id),
            type=failed.event_type,
            headers={
                "traceId": str(failed.trace_id),
                "taskId": str(failed.task_id),
                "tripId": str(failed.trip_id),
                "runId": str(failed.run_id),
            },
        )
        try:
            await event_exchange.publish(
                outgoing,
                routing_key=FAILED_ROUTING_KEY,
                mandatory=True,
            )
        except Exception:
            logger.exception("planning failure event was not confirmed")
            if cancellation_registry is not None:
                cancellation_registry.finish(command.task_id)
            await message.nack(requeue=True)
            return
    except Exception:
        logger.exception("planning command failed before completion event was confirmed")
        if cancellation_registry is not None:
            cancellation_registry.finish(command.task_id)
        await message.nack(requeue=True)
        return

    await message.ack()
    if cancellation_registry is not None:
        cancellation_registry.finish(command.task_id)


async def handle_cancel_delivery(
    message: IncomingDelivery,
    cancellation_registry: CancellationRegistry,
) -> None:
    try:
        command = PlanningCancelCommand.model_validate_json(message.body)
    except (ValidationError, TypeError, ValueError) as exception:
        error_count = exception.error_count() if isinstance(exception, ValidationError) else 1
        logger.warning("rejecting invalid planning cancel command: %s", error_count)
        await message.reject(requeue=False)
        return
    cancellation_registry.cancel(command.task_id)
    await message.ack()


async def run_worker(settings: WorkerSettings) -> None:
    async with worker_runtime(settings) as runtime:
        await _consume(
            settings,
            runtime.planning_provider,
            runtime.knowledge_provider,
            runtime.cancellation_oracle,
        )


async def _consume(
    settings: WorkerSettings,
    provider: PlanningProvider,
    knowledge_provider: KnowledgeEvidenceProvider,
    cancellation_oracle: CancellationOracle,
) -> None:
    connection = await aio_pika.connect_robust(
        host=settings.rabbitmq_host,
        port=settings.rabbitmq_port,
        login=settings.rabbitmq_user,
        password=settings.rabbitmq_password,
    )
    async with connection:
        channel = await connection.channel(publisher_confirms=True, on_return_raises=True)
        await channel.set_qos(prefetch_count=1)
        control_channel = await connection.channel()
        await control_channel.set_qos(prefetch_count=100)
        command_exchange = await channel.declare_exchange(
            COMMAND_EXCHANGE, aio_pika.ExchangeType.DIRECT, durable=True
        )
        event_exchange = await channel.declare_exchange(
            EVENT_EXCHANGE, aio_pika.ExchangeType.DIRECT, durable=True
        )
        dead_letter_exchange = await channel.declare_exchange(
            DEAD_LETTER_EXCHANGE, aio_pika.ExchangeType.TOPIC, durable=True
        )
        command_queue = await channel.declare_queue(
            CREATE_QUEUE,
            durable=True,
            arguments={
                "x-dead-letter-exchange": DEAD_LETTER_EXCHANGE,
                "x-dead-letter-routing-key": DEAD_LETTER_ROUTING_KEY,
            },
        )
        cancel_queue = await control_channel.declare_queue(
            CANCEL_QUEUE,
            durable=True,
            arguments={
                "x-dead-letter-exchange": DEAD_LETTER_EXCHANGE,
                "x-dead-letter-routing-key": CANCEL_DEAD_LETTER_ROUTING_KEY,
            },
        )
        dead_letter_queue = await channel.declare_queue(DEAD_LETTER_QUEUE, durable=True)
        await command_queue.bind(command_exchange, routing_key=CREATE_ROUTING_KEY)
        await cancel_queue.bind(command_exchange, routing_key=CANCEL_ROUTING_KEY)
        await dead_letter_queue.bind(dead_letter_exchange, routing_key="planning.#")
        cancellation_registry = CancellationRegistry()
        callback: Callable[[AbstractIncomingMessage], Awaitable[None]] = partial(
            _handle_incoming,
            event_exchange=event_exchange,
            provider=provider,
            knowledge_provider=knowledge_provider,
            cancellation_registry=cancellation_registry,
            cancellation_oracle=cancellation_oracle,
        )
        cancel_callback: Callable[[AbstractIncomingMessage], Awaitable[None]] = partial(
            _handle_cancel_incoming,
            cancellation_registry=cancellation_registry,
        )
        await cancel_queue.consume(cancel_callback)
        await command_queue.consume(callback)
        logger.info("planning worker consuming queues=%s,%s", CREATE_QUEUE, CANCEL_QUEUE)
        await asyncio.Future()


async def _handle_incoming(
    message: AbstractIncomingMessage,
    *,
    event_exchange: AbstractExchange,
    provider: PlanningProvider,
    knowledge_provider: KnowledgeEvidenceProvider,
    cancellation_registry: CancellationRegistry,
    cancellation_oracle: CancellationOracle,
) -> None:
    await handle_delivery(
        message,
        event_exchange,
        provider,
        knowledge_provider,
        cancellation_registry,
        cancellation_oracle,
    )


async def _handle_cancel_incoming(
    message: AbstractIncomingMessage,
    *,
    cancellation_registry: CancellationRegistry,
) -> None:
    await handle_cancel_delivery(message, cancellation_registry)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_worker(WorkerSettings()))


if __name__ == "__main__":
    main()
