"""AMQP transport for the planning worker."""

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any, Literal, Protocol, Self
from urllib.parse import quote
from uuid import NAMESPACE_URL, UUID, uuid5

import aio_pika
import httpx
import psycopg
from aio_pika.abc import AbstractExchange, AbstractIncomingMessage
from pydantic import Field, SecretStr, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from trip_agent.acquisition.registry import SourceCatalog
from trip_agent.application.candidate_validation import CandidateValidationProvider
from trip_agent.domain.planning.protocols import (
    KnowledgeEvidenceProvider,
    PlanningInfeasibleError,
    PlanningProvider,
    PlanningProviderError,
)
from trip_agent.infrastructure.amap.planning_provider import AmapPlanningProvider
from trip_agent.infrastructure.demo.knowledge_provider import DemoKnowledgeEvidenceProvider
from trip_agent.infrastructure.demo.planning_provider import DemoPlanningProvider
from trip_agent.platform_util import run_async
from trip_agent.providers.errors import (
    ProviderErrorCategory,
    ProviderExecutionMode,
    ProviderFallbackPolicy,
)
from trip_agent.providers.map import AmapMapProvider, JsonCache
from trip_agent.providers.redis_cache import RedisJsonCache
from trip_agent.providers.retry import (
    ProviderRetryPolicy,
    RetryingMapProvider,
    RetryingRouteProvider,
)
from trip_agent.providers.route import AmapRouteProvider, DemoRouteProvider
from trip_agent.retrieval.embeddings import (
    DashScopeEmbeddingProvider,
    EmbeddingProvider,
    HashEmbeddingProvider,
)
from trip_agent.retrieval.repository import PsycopgKnowledgeRepository
from trip_agent.worker.contracts import (
    PlanningCancelCommand,
    PlanningCandidateValidationCommand,
    PlanningCreateCommand,
    PlanningProgressEvent,
    PlanningProgressPayload,
    PlanningProgressStage,
    PlanningReplanCommand,
)
from trip_agent.worker.knowledge import (
    KnowledgeFreshnessProvider,
    KnowledgeSearchRepository,
    RetrievalKnowledgeEvidenceProvider,
    StaticCatalogKnowledgeFreshnessProvider,
)
from trip_agent.worker.processor import (
    planning_failed_event,
    process_candidate_validation,
    process_planning_create,
    process_planning_replan,
)
from trip_agent.worker.progress import planning_progress_reporting
from trip_agent.workflow.planner_pipeline import FallbackPlanningProvider

COMMAND_EXCHANGE = "trip.command.exchange"
EVENT_EXCHANGE = "trip.event.exchange"
DEAD_LETTER_EXCHANGE = "trip.dead-letter.exchange"
CREATE_QUEUE = "planning.create.queue"
CANCEL_QUEUE = "planning.cancel.queue"
DEAD_LETTER_QUEUE = "planning.dead-letter.queue"
CREATE_ROUTING_KEY = "planning.create"
REPLAN_ROUTING_KEY = "planning.replan"
CANDIDATE_VALIDATION_ROUTING_KEY = "planning.candidate-validation"
CANCEL_ROUTING_KEY = "planning.cancel"
COMPLETED_ROUTING_KEY = "planning.completed"
REVIEW_REQUIRED_ROUTING_KEY = "planning.review-required"
FAILED_ROUTING_KEY = "planning.failed"
PROGRESS_ROUTING_KEY = "planning.progress"
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


@dataclass(slots=True)
class PlanningProgressPublisher:
    """Publishes each observed worker milestone once per planning command."""

    event_exchange: EventExchange
    command: PlanningCreateCommand | PlanningReplanCommand | PlanningCandidateValidationCommand
    _emitted_stages: set[PlanningProgressStage] = field(default_factory=set)
    _last_stage_rank: int = 0
    _sequence: int = 0

    _stage_order = (
        "TASK_ACCEPTED",
        "CONTEXT_VALIDATING",
        "CITY_FACTS_LOADING",
        "POI_RECALLING",
        "CANDIDATES_RANKING",
        "ROUTES_CALCULATING",
        "CONSTRAINTS_SOLVING",
        "REPAIRING",
        "KNOWLEDGE_RETRIEVING",
        "RESULT_EXPLAINING",
        "RESULT_PUBLISHING",
    )
    _stage_progress = {
        "TASK_ACCEPTED": 5,
        "CONTEXT_VALIDATING": 15,
        "CITY_FACTS_LOADING": 25,
        "POI_RECALLING": 35,
        "CANDIDATES_RANKING": 45,
        "ROUTES_CALCULATING": 55,
        "CONSTRAINTS_SOLVING": 65,
        "REPAIRING": 75,
        "KNOWLEDGE_RETRIEVING": 75,
        "RESULT_EXPLAINING": 85,
        "RESULT_PUBLISHING": 95,
    }

    async def report(
        self,
        stage: PlanningProgressStage,
        message: str,
        statistics: Mapping[str, int] | None = None,
    ) -> None:
        repeated_repair = stage == "REPAIRING"
        if stage in self._emitted_stages and not repeated_repair:
            return
        rank = self._stage_order.index(stage) + 1
        if rank < self._last_stage_rank:
            logger.warning(
                "ignoring regressive planning stage task_id=%s stage=%s",
                self.command.task_id,
                stage,
            )
            return
        self._sequence += 1
        event = PlanningProgressEvent(
            event_type="PLANNING_PROGRESS",
            schema_version=2,
            event_id=uuid5(
                NAMESPACE_URL,
                f"trip-pilot/planning-progress/{self.command.event_id}/{stage}/{self._sequence}",
            ),
            trace_id=self.command.trace_id,
            task_id=self.command.task_id,
            trip_id=self.command.trip_id,
            occurred_at=datetime.now(UTC),
            payload=PlanningProgressPayload(
                stage=stage,
                sequence=self._sequence,
                progress=self._stage_progress[stage],
                message=message,
                statistics=dict(statistics or {}),
            ),
        )
        outgoing = aio_pika.Message(
            body=event.model_dump_json(by_alias=True, exclude_none=True).encode(),
            content_type="application/json",
            content_encoding="utf-8",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            message_id=str(event.event_id),
            correlation_id=str(event.trace_id),
            type=event.event_type,
            headers={
                "traceId": str(event.trace_id),
                "taskId": str(event.task_id),
                "tripId": str(event.trip_id),
            },
        )
        await self.event_exchange.publish(
            outgoing,
            routing_key=PROGRESS_ROUTING_KEY,
            mandatory=True,
        )
        if not repeated_repair:
            self._emitted_stages.add(stage)
        self._last_stage_rank = rank


class PsycopgCancellationOracle:
    """Checks cancellation status via a persistent database connection.

    Uses a single long-lived async connection instead of opening a new
    connection per check, avoiding connection-storm under load.
    """

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url
        self._connection: psycopg.AsyncConnection | None = None

    async def _ensure_connection(self) -> psycopg.AsyncConnection:
        if self._connection is None or self._connection.closed:
            self._connection = await psycopg.AsyncConnection.connect(self._database_url)
        return self._connection

    async def is_cancelled(self, task_id: UUID) -> bool:
        try:
            connection = await self._ensure_connection()
            async with connection.cursor() as cursor:
                await cursor.execute(
                    "SELECT status FROM business.planning_task WHERE id = %s",
                    (task_id,),
                )
                row = await cursor.fetchone()
        except psycopg.Error:
            # Connection may have dropped — reset and let the next call
            # re-establish it.
            self._connection = None
            raise
        return row is not None and row[0] == "CANCELLED"

    async def close(self) -> None:
        if self._connection is not None and not self._connection.closed:
            await self._connection.close()


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
    provider_mode: ProviderExecutionMode | None = None
    demo_mode: bool | None = None
    amap_web_service_key: SecretStr | None = None
    amap_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    provider_max_attempts: int = Field(default=3, ge=1, le=5)
    provider_retry_base_delay_seconds: float = Field(default=0.2, ge=0, le=5)
    provider_retry_max_delay_seconds: float = Field(default=2.0, ge=0, le=30)
    provider_retry_max_elapsed_seconds: float = Field(default=5.0, gt=0, le=60)
    provider_retry_jitter_ratio: float = Field(default=0.2, ge=0, le=1)
    provider_fallback_categories: frozenset[ProviderErrorCategory] = frozenset()
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
    dashscope_embedding_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    dashscope_embedding_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    knowledge_source_directory: Path = Path("../../knowledge/sources")
    postgres_host: str = "localhost"
    postgres_port: int = Field(default=5432, ge=1, le=65_535)
    postgres_db: str = "trip_pilot"
    postgres_user: str = "trip_pilot"
    postgres_password: SecretStr = SecretStr("local-development-only")

    @model_validator(mode="after")
    def require_real_provider_key(self) -> Self:
        if self.provider_mode is not None and self.demo_mode is not None:
            legacy_mode = (
                ProviderExecutionMode.DEMO_ONLY
                if self.demo_mode
                else ProviderExecutionMode.REAL_ONLY
            )
            if self.provider_mode != legacy_mode:
                raise ValueError("PROVIDER_MODE conflicts with DEMO_MODE")
        ProviderFallbackPolicy(additional_allowed_categories=self.provider_fallback_categories)
        key = self.amap_web_service_key
        if self.resolved_provider_mode != ProviderExecutionMode.DEMO_ONLY and (
            key is None or not key.get_secret_value().strip()
        ):
            raise ValueError("AMAP_WEB_SERVICE_KEY is required in a real provider mode")
        embedding_key = self.dashscope_api_key
        if (
            self.resolved_provider_mode != ProviderExecutionMode.DEMO_ONLY
            and self.knowledge_embedding_provider == "dashscope"
            and (embedding_key is None or not embedding_key.get_secret_value().strip())
        ):
            raise ValueError("DASHSCOPE_API_KEY is required for DashScope embeddings")
        return self

    @property
    def resolved_provider_mode(self) -> ProviderExecutionMode:
        if self.provider_mode is not None:
            return self.provider_mode
        if self.demo_mode is not None:
            return (
                ProviderExecutionMode.DEMO_ONLY
                if self.demo_mode
                else ProviderExecutionMode.REAL_ONLY
            )
        return ProviderExecutionMode.DEMO_ONLY

    def provider_retry_policy(self) -> ProviderRetryPolicy:
        return ProviderRetryPolicy(
            max_attempts=self.provider_max_attempts,
            base_delay_seconds=self.provider_retry_base_delay_seconds,
            max_delay_seconds=self.provider_retry_max_delay_seconds,
            max_elapsed_seconds=self.provider_retry_max_elapsed_seconds,
            jitter_ratio=self.provider_retry_jitter_ratio,
        )

    def provider_fallback_policy(self) -> ProviderFallbackPolicy:
        return ProviderFallbackPolicy(
            additional_allowed_categories=self.provider_fallback_categories
        )

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
    mode = settings.resolved_provider_mode
    if mode == ProviderExecutionMode.DEMO_ONLY:
        return DemoPlanningProvider()
    if http_client is None:
        raise ValueError("HTTP client is required in real provider mode")
    key = settings.amap_web_service_key
    if key is None:
        raise ValueError("AMap key is required in real provider mode")
    retry_policy = settings.provider_retry_policy()
    amap_map = RetryingMapProvider(
        AmapMapProvider(
            api_key=key.get_secret_value(),
            http_client=http_client,
            cache=cache,
            cache_ttl_seconds=settings.poi_cache_ttl_seconds,
        ),
        retry_policy,
    )
    amap_route = RetryingRouteProvider(
        AmapRouteProvider(
            api_key=key.get_secret_value(),
            http_client=http_client,
            cache=cache,
            cache_ttl_seconds=settings.route_cache_ttl_seconds,
        ),
        retry_policy,
    )
    policy = settings.provider_fallback_policy()
    primary = AmapPlanningProvider(
        amap_map,
        amap_route,
        route_fallback=(
            DemoRouteProvider()
            if mode == ProviderExecutionMode.REAL_WITH_EXPLICIT_FALLBACK
            else None
        ),
        provider_mode=mode,
        fallback_policy=policy,
    )
    if mode == ProviderExecutionMode.REAL_ONLY:
        return primary
    return FallbackPlanningProvider(
        primary,
        DemoPlanningProvider(),
        provider_mode=mode,
        fallback_policy=policy,
    )


def build_knowledge_provider(
    settings: WorkerSettings,
    *,
    embedding_provider: EmbeddingProvider | None = None,
    repository: KnowledgeSearchRepository | None = None,
    freshness_provider: KnowledgeFreshnessProvider | None = None,
) -> KnowledgeEvidenceProvider:
    if settings.resolved_provider_mode == ProviderExecutionMode.DEMO_ONLY:
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
    logger.info("provider_mode=%s", settings.resolved_provider_mode.value)
    if settings.resolved_provider_mode == ProviderExecutionMode.DEMO_ONLY:
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
            cancellation_oracle=PsycopgCancellationOracle(settings.business_connection_url()),
        )


async def handle_delivery(
    message: IncomingDelivery,
    event_exchange: EventExchange,
    provider: PlanningProvider | None = None,
    knowledge_provider: KnowledgeEvidenceProvider | None = None,
    cancellation_registry: CancellationRegistry | None = None,
    cancellation_oracle: CancellationOracle | None = None,
) -> None:
    processing_command = False
    try:
        raw_command: Any = json.loads(message.body)
        if not isinstance(raw_command, dict):
            raise ValueError("planning command must be a JSON object")
        event_type = raw_command.get("eventType")
        if event_type == "PLANNING_REPLAN_REQUESTED":
            command = PlanningReplanCommand.model_validate(raw_command)
        elif event_type == "PLANNING_CANDIDATE_VALIDATION_REQUESTED":
            command = PlanningCandidateValidationCommand.model_validate(raw_command)
        else:
            command = PlanningCreateCommand.model_validate(raw_command)
    except (ValidationError, TypeError, ValueError) as exception:
        error_count = exception.error_count() if isinstance(exception, ValidationError) else 1
        logger.warning("rejecting invalid planning command: %s", error_count)
        await message.reject(requeue=False)
        return

    try:
        planning_provider = provider or DemoPlanningProvider()
        progress_publisher = PlanningProgressPublisher(event_exchange, command)
        if cancellation_registry is not None:
            signal = cancellation_registry.signal_for(command.task_id)
            if signal.is_set():
                cancellation_registry.finish(command.task_id)
                await message.ack()
                return
        if await _is_cancelled(command.task_id, cancellation_registry, cancellation_oracle):
            if cancellation_registry is not None:
                cancellation_registry.finish(command.task_id)
            await message.ack()
            return
        async with planning_progress_reporting(progress_publisher.report):
            await progress_publisher.report(
                "TASK_ACCEPTED",
                "Planning task accepted by the worker",
                {
                    "tripDays": (
                        command.payload.trip.end_date - command.payload.trip.start_date
                    ).days
                    + 1,
                },
            )
            processing_command = True
            if isinstance(command, PlanningCandidateValidationCommand):
                process_task = asyncio.create_task(
                    process_candidate_validation(
                        command,
                        CandidateValidationProvider(planning_provider),
                    )
                )
            elif isinstance(command, PlanningReplanCommand):
                process_task = asyncio.create_task(
                    process_planning_replan(
                        command,
                        planning_provider,
                    )
                )
            else:
                process_task = asyncio.create_task(
                    process_planning_create(
                        command,
                        planning_provider,
                        knowledge_provider=knowledge_provider,
                    )
                )
            cancel_wait: asyncio.Task[bool] | None = None
            if cancellation_registry is not None:
                signal = cancellation_registry.signal_for(command.task_id)
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
            processing_command = False
            if await _is_cancelled(command.task_id, cancellation_registry, cancellation_oracle):
                if cancellation_registry is not None:
                    cancellation_registry.finish(command.task_id)
                await message.ack()
                return
            await progress_publisher.report(
                "RESULT_PUBLISHING",
                "Publishing the planning result",
            )
            outgoing = aio_pika.Message(
                body=completed.model_dump_json(by_alias=True, exclude_none=False).encode(),
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
            routing_key = (
                COMPLETED_ROUTING_KEY
                if completed.event_type == "PLANNING_COMPLETED"
                else REVIEW_REQUIRED_ROUTING_KEY
            )
            await event_exchange.publish(
                outgoing,
                routing_key=routing_key,
                mandatory=True,
            )
    except (PlanningInfeasibleError, PlanningProviderError) as failure:
        await _publish_terminal_failure(
            message,
            event_exchange,
            command,
            failure,
            cancellation_registry,
            cancellation_oracle,
        )
        return
    except Exception as failure:
        if processing_command:
            logger.exception("planning command ended with a non-retryable internal error")
            await _publish_terminal_failure(
                message,
                event_exchange,
                command,
                failure,
                cancellation_registry,
                cancellation_oracle,
            )
            return
        logger.exception("planning command failed before completion event was confirmed")
        if cancellation_registry is not None:
            cancellation_registry.finish(command.task_id)
        await message.nack(requeue=True)
        return

    await message.ack()
    if cancellation_registry is not None:
        cancellation_registry.finish(command.task_id)


async def _publish_terminal_failure(
    message: IncomingDelivery,
    event_exchange: EventExchange,
    command: PlanningCreateCommand | PlanningReplanCommand | PlanningCandidateValidationCommand,
    failure: Exception,
    cancellation_registry: CancellationRegistry | None,
    cancellation_oracle: CancellationOracle | None,
) -> None:
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
        await command_queue.bind(command_exchange, routing_key=REPLAN_ROUTING_KEY)
        await command_queue.bind(
            command_exchange, routing_key=CANDIDATE_VALIDATION_ROUTING_KEY
        )
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
    run_async(run_worker(WorkerSettings()))


if __name__ == "__main__":
    main()
