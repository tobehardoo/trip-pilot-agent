"""AMQP transport for the planning worker."""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import partial
from typing import Any, Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

import aio_pika
from aio_pika.abc import AbstractExchange, AbstractIncomingMessage
from pydantic import ValidationError

from trip_agent.application.candidate_validation import CandidateValidationProvider
from trip_agent.domain.planning.protocols import (
    KnowledgeEvidenceProvider,
    PlanningInfeasibleError,
    PlanningProvider,
    PlanningProviderError,
)
from trip_agent.infrastructure.demo.planning_provider import DemoPlanningProvider
from trip_agent.platform_util import run_async
from trip_agent.worker.agent_processor import (
    AGENT_DEAD_LETTER_ROUTING_KEY,
    AGENT_DIALOG_QUEUE,
    AGENT_RESUME_ROUTING_KEY,
    AGENT_START_ROUTING_KEY,
    handle_agent_delivery,
)
from trip_agent.worker.contracts import (
    PlanningCancelCommand,
    PlanningCandidateValidationCommand,
    PlanningCreateCommand,
    PlanningProgressEvent,
    PlanningProgressPayload,
    PlanningProgressStage,
    PlanningReplanCommand,
)
from trip_agent.worker.processor import (
    planning_failed_event,
    process_candidate_validation,
    process_planning_create,
    process_planning_replan,
)
from trip_agent.worker.progress import planning_progress_reporting
from trip_agent.worker.runtime import (
    CancellationOracle,
    WorkerSettings,
    worker_runtime,
)
from trip_agent.worker.structured_logging import planning_logger

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
        # B13_FIX R2 (P0-2): a malformed command with an identifiable task
        # must reach a safe terminal FAILED state, never stay QUEUED.
        await _publish_command_validation_failure(
            message,
            event_exchange,
            raw_command,
            cancellation_registry,
            cancellation_oracle,
        )
        return

    planning_logger(
        "trip_agent.worker",
        trace_id=str(command.trace_id),
        event_id=str(command.event_id),
        task_id=str(command.task_id),
        trip_id=str(command.trip_id),
    ).info("command received: %s", command.event_type)

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


def _extract_command_identity(raw_command: dict) -> dict | None:
    """Best-effort envelope identity from an invalid raw command.

    Returns None when the task cannot be identified; the message is then
    dead-lettered because no failure event could ever reach its task.
    """
    try:
        identity = {
            key: UUID(str(raw_command[key]))
            for key in ("eventId", "traceId", "taskId", "tripId")
        }
    except (KeyError, TypeError, ValueError):
        return None
    return identity


async def _publish_command_validation_failure(
    message: IncomingDelivery,
    event_exchange: EventExchange,
    raw_command: dict,
    cancellation_registry: CancellationRegistry | None,
    cancellation_oracle: CancellationOracle | None,
) -> None:
    """Publish a safe PLANNING_FAILED for an unparseable command.

    The failure is terminal and idempotent: the event id derives
    deterministically from the raw eventId, the payload carries a stable
    error category/code and never the raw body, and Java applies it
    atomically (QUEUED/RUNNING → FAILED, duplicate eventIds ignored).
    """
    from datetime import UTC, datetime

    from trip_agent.worker.contracts import PlanningFailedEvent, PlanningFailedPayload
    from trip_agent.worker.processor import _failed_event_id, _run_id

    identity = _extract_command_identity(raw_command)
    if identity is None:
        # No task can be identified: dead-letter without a failure event.
        await message.reject(requeue=False)
        return
    cancelled = await _is_cancelled(
        identity["taskId"],
        cancellation_registry,
        cancellation_oracle,
    )
    if cancelled:
        if cancellation_registry is not None:
            cancellation_registry.finish(identity["taskId"])
        await message.ack()
        return
    failed = PlanningFailedEvent(
        event_type="PLANNING_FAILED",
        schema_version=2,
        event_id=_failed_event_id(identity["eventId"]),
        trace_id=identity["traceId"],
        task_id=identity["taskId"],
        trip_id=identity["tripId"],
        run_id=_run_id(identity["taskId"]),
        occurred_at=datetime.now(UTC),
        payload=PlanningFailedPayload(
            status="FAILED",
            error_code="COMMAND_VALIDATION_FAILED",
            error_category="INVALID_REQUEST",
            provider="PLANNER",
            operation="PLANNING",
            retryable=False,
            retry_count=0,
            fallback_attempted=False,
            fallback_succeeded=False,
            safe_message="规划命令无法解析，请调整行程条件后重新规划",
            safe_provider_code=None,
            cause_type=None,
            conflicts=(),
            relaxation_suggestions=(),
        ),
    )
    planning_logger(
        "trip_agent.worker",
        trace_id=str(failed.trace_id),
        event_id=str(failed.event_id),
        task_id=str(failed.task_id),
        trip_id=str(failed.trip_id),
    ).warning(
        "outcome emitted: PLANNING_FAILED",
        extra={"outcome_status": "FAILED", "reason_code": "COMMAND_VALIDATION_FAILED"},
    )
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
            cancellation_registry.finish(identity["taskId"])
        await message.nack(requeue=True)
        return
    await message.ack()
    if cancellation_registry is not None:
        cancellation_registry.finish(identity["taskId"])


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
    planning_logger(
        "trip_agent.worker",
        trace_id=str(failed.trace_id),
        event_id=str(failed.event_id),
        task_id=str(failed.task_id),
        trip_id=str(failed.trip_id),
    ).warning(
        "outcome emitted: PLANNING_FAILED",
        extra={"outcome_status": "FAILED", "reason_code": failed.payload.error_code},
    )
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
        agent_queue = await channel.declare_queue(
            AGENT_DIALOG_QUEUE,
            durable=True,
            arguments={
                "x-dead-letter-exchange": DEAD_LETTER_EXCHANGE,
                "x-dead-letter-routing-key": AGENT_DEAD_LETTER_ROUTING_KEY,
            },
        )
        await command_queue.bind(command_exchange, routing_key=CREATE_ROUTING_KEY)
        await command_queue.bind(command_exchange, routing_key=REPLAN_ROUTING_KEY)
        await command_queue.bind(command_exchange, routing_key=CANDIDATE_VALIDATION_ROUTING_KEY)
        await cancel_queue.bind(command_exchange, routing_key=CANCEL_ROUTING_KEY)
        await agent_queue.bind(command_exchange, routing_key=AGENT_START_ROUTING_KEY)
        await agent_queue.bind(command_exchange, routing_key=AGENT_RESUME_ROUTING_KEY)
        await dead_letter_queue.bind(dead_letter_exchange, routing_key="planning.#")
        await dead_letter_queue.bind(dead_letter_exchange, routing_key="agent.#")
        cancellation_registry = CancellationRegistry()
        callback: Callable[[AbstractIncomingMessage], Awaitable[None]] = partial(
            _handle_incoming,
            event_exchange=event_exchange,
            provider=provider,
            knowledge_provider=knowledge_provider,
            cancellation_registry=cancellation_registry,
            cancellation_oracle=cancellation_oracle,
        )
        agent_callback: Callable[[AbstractIncomingMessage], Awaitable[None]] = partial(
            _handle_agent_incoming,
            event_exchange=event_exchange,
        )
        cancel_callback: Callable[[AbstractIncomingMessage], Awaitable[None]] = partial(
            _handle_cancel_incoming,
            cancellation_registry=cancellation_registry,
        )
        await cancel_queue.consume(cancel_callback)
        await command_queue.consume(callback)
        await agent_queue.consume(agent_callback)
        logger.info(
            "planning worker consuming queues=%s,%s,%s",
            CREATE_QUEUE,
            CANCEL_QUEUE,
            AGENT_DIALOG_QUEUE,
        )
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


async def _handle_agent_incoming(
    message: AbstractIncomingMessage,
    *,
    event_exchange: AbstractExchange,
) -> None:
    await handle_agent_delivery(message, event_exchange)


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
