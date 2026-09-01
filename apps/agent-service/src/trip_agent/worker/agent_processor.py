"""P2.1: the agent dialog path — AGENT_START / AGENT_RESUME drive bounded runs.

Each dialog command is one bounded agent run (ADR-016): trajectory and
checkpoints land through the P1.6/P1.7 recorder, and a WAITING_USER outcome
is announced to the backend as an AGENT_ASK_USER event (P1.8 contract).  A
resume restores the checkpoint, injects the user's verbatim answer as the
working message and continues the loop.  Planning commands never enter this
module, and agent commands never enter the planning failure chain.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID, uuid4

import aio_pika

from trip_agent.agent import (
    AgentLoop,
    AgentRunRecorder,
    AgentRunResult,
    AgentState,
    PsycopgAgentRunRepository,
    ToolRegistry,
    ToolRuntime,
    build_decision_maker,
    run_agent,
)
from trip_agent.agent.feasibility_gate import StructuralFeasibilityGate
from trip_agent.agent.itinerary_builder import (
    DemoItineraryBuilder,
    RealItineraryBuilder,
)
from trip_agent.agent.profile import TravelProfileRepository
from trip_agent.agent.tool_capabilities import build_observation_capabilities
from trip_agent.worker.contracts import (
    AgentAskUserEvent,
    AgentCompletedEvent,
    AgentResumeCommand,
    AgentRunFinishedEvent,
    AgentStartCommand,
    AgentStepEvent,
    Itinerary,
)

logger = logging.getLogger("trip_agent.worker")

AGENT_DIALOG_QUEUE = "agent.dialog.queue"
AGENT_START_ROUTING_KEY = "agent.start"
AGENT_RESUME_ROUTING_KEY = "agent.resume"
AGENT_ASK_USER_ROUTING_KEY = "agent.ask-user"
AGENT_STEP_ROUTING_KEY = "agent.step"
AGENT_COMPLETED_ROUTING_KEY = "agent.completed"
AGENT_RUN_FINISHED_ROUTING_KEY = "agent.run-finished"
AGENT_DEAD_LETTER_ROUTING_KEY = "agent.dialog.dead"

_EVENT_ROUTING_KEYS = {
    "AGENT_ASK_USER": AGENT_ASK_USER_ROUTING_KEY,
    "AGENT_STEP": AGENT_STEP_ROUTING_KEY,
    "AGENT_COMPLETED": AGENT_COMPLETED_ROUTING_KEY,
    "AGENT_RUN_FINISHED": AGENT_RUN_FINISHED_ROUTING_KEY,
}

_WIRE_EXPECTED_TYPES = {
    "text": "TEXT",
    "number": "NUMBER",
    "date": "DATE",
    "choice": "CHOICE",
}

# User-safe copy for terminals that carry no question and no itinerary.  The
# technical cause stays in logs/trajectory; the user only ever sees these.
_STOP_MESSAGES = {
    "CEILING_REACHED": "这次处理达到了单轮步骤上限，未能完成你的请求。可以换个说法再试一次。",
}
_STOP_DEFAULT_MESSAGE = "这次没能完成你的请求，请重新发起。"
_ANSWER_DEFAULT_MESSAGE = "本轮对话已结束。"

_RESUME_REJECTION_MESSAGES = {
    "RUN_EXPIRED": "这次对话搁置太久已自动结束，重新发起即可继续。",
    "RUN_IN_PROGRESS": "助手正在处理中，这条回复没有送达，稍等片刻即可看到结果。",
    "RUN_TERMINAL": "这次对话已经结束，这条回复没有送达。重新发起即可开始新的规划。",
    "RUN_UNKNOWN": "没有找到对应的对话任务，请重新发起。",
    "NO_CHECKPOINT": "这次对话的状态已丢失，请重新发起。",
}


class AgentResumeRejected(Exception):
    """A resume that cannot continue its run, with a stable reason code.

    Reason codes (P3.1): ``RUN_UNKNOWN`` / ``RUN_EXPIRED`` / ``RUN_IN_PROGRESS``
    / ``RUN_TERMINAL`` / ``NO_CHECKPOINT`` / ``INCOMPLETE``.
    """

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(f"{reason}: {message}")
        self.reason = reason


class DialogEventExchange(Protocol):
    """The slice of the aio-pika exchange the dialog path publishes on."""

    async def publish(
        self, message: Any, *, routing_key: str, mandatory: bool = True
    ) -> None: ...


DialogEvent = (
    AgentAskUserEvent | AgentStepEvent | AgentCompletedEvent | AgentRunFinishedEvent
)
Publisher = Callable[[DialogEvent], Awaitable[None]]
LoopFactory = Callable[[], AgentLoop]


@dataclass(frozen=True, slots=True)
class AgentRunLifecycleConfig:
    """Resumability windows for dialog runs (P3.1).

    A WAITING_USER run stays answerable for ``waiting_ttl_seconds``; after
    that a resume marks it EXPIRED instead of continuing it.  A RUNNING run
    whose checkpoint has not ticked for ``running_stale_seconds`` is treated
    as crash-orphaned and may be recovered; a fresh one may still be executing
    elsewhere, so a resume is refused to prevent double execution.
    """

    waiting_ttl_seconds: float = 7 * 24 * 3600
    running_stale_seconds: float = 600

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> AgentRunLifecycleConfig:
        source = os.environ if env is None else env

        def _seconds(name: str, default: float) -> float:
            raw = source.get(name, "").strip()
            return float(raw) if raw else default

        return cls(
            waiting_ttl_seconds=_seconds("AGENT_WAITING_TTL_SECONDS", 7 * 24 * 3600),
            running_stale_seconds=_seconds("AGENT_RUNNING_STALE_SECONDS", 600),
        )


def _default_loop_registry() -> ToolRegistry:
    return ToolRegistry.with_runtime(
        ToolRuntime(
            itinerary_builder=DemoItineraryBuilder(),
            feasibility=StructuralFeasibilityGate(),
        )
    )


def default_loop_factory() -> AgentLoop:
    """The production loop: shared-credential decider over wired capabilities.

    The demo builder and the structural gate run without provider keys
    (ADR-007); the real-provider builder and the Hard-Validation-parity gate
    upgrade through the same seams.
    """
    registry = _default_loop_registry()
    return AgentLoop(decider=build_decision_maker(tools=registry), tools=registry)


class AgentDialogProcessor:
    """Runs one bounded agent turn per dialog command."""

    def __init__(
        self,
        *,
        repository: PsycopgAgentRunRepository,
        publisher: Publisher,
        loop_factory: LoopFactory = default_loop_factory,
        lifecycle: AgentRunLifecycleConfig | None = None,
        profile_store: Any | None = None,
    ) -> None:
        self._repository = repository
        self._publisher = publisher
        self._loop_factory = loop_factory
        self._lifecycle = lifecycle or AgentRunLifecycleConfig.from_env()
        self._profile_store = profile_store

    async def _load_preferences(
        self, user_id: str | None
    ) -> tuple[tuple[str, str], ...]:
        """Confirmed preferences for the run's user (P3.2); empty when absent."""
        if not user_id or self._profile_store is None:
            return ()
        records = await self._profile_store.list_confirmed(user_id)
        return tuple((record.category, record.value) for record in records)

    async def handle_start(self, command: AgentStartCommand) -> AgentRunResult | None:
        run_id = str(uuid4())
        recorder = AgentRunRecorder(
            self._repository,
            run_id=run_id,
            command_event_id=str(command.event_id),
            trip_id=str(command.trip_id),
        )
        started = await recorder.start()
        if not started.created:
            # A redelivered AGENT_START must not spawn a second run.
            logger.info("agent_start_deduplicated run_id=%s", started.run_id)
            return None
        state = AgentState(
            user_message=command.payload.message,
            trip_id=str(command.trip_id),
            user_id=str(command.user_id) if command.user_id else None,
            confirmed_preferences=await self._load_preferences(
                str(command.user_id) if command.user_id else None
            ),
        )
        result = await run_agent(
            self._loop_factory(),
            state,
            checkpoint_sink=self._dialog_sink(
                recorder, command, run_id, baseline_observations=len(state.observations)
            ),
        )
        question_published = await self._publish_question(result, run_id, command)
        completion_published = await self._publish_completion(result, run_id, command)
        if not question_published and not completion_published:
            # A terminal without a question and without an itinerary used to
            # be invisible (P0): the frontend would wait forever.  Ceiling
            # stops and plain answers now close the turn on the wire.
            await self._publish_run_finished(result, run_id, command)
        await recorder.finish(result)
        return result

    async def handle_resume(self, command: AgentResumeCommand) -> AgentRunResult:
        run_id = str(command.run_id)
        record = await self._repository.load_run(run_id)
        if record is None:
            raise AgentResumeRejected("RUN_UNKNOWN", f"unknown agent run: {run_id}")

        if record.status == "WAITING_USER":
            waited = self._seconds_since(getattr(record, "updated_at", None))
            if waited is not None and waited > self._lifecycle.waiting_ttl_seconds:
                await self._repository.finish_run(
                    run_id=run_id,
                    status="EXPIRED",
                    stop_reason="RUN_EXPIRED",
                    answer=None,
                    pending_question=None,
                )
                raise AgentResumeRejected(
                    "RUN_EXPIRED",
                    f"agent run {run_id} waited {waited:.0f}s beyond the resumable window",
                )
        elif record.status == "RUNNING":
            # A RUNNING run may be crash-orphaned.  A fresh checkpoint means a
            # worker is likely still ticking it — refuse to prevent double
            # execution; a stale one is recovered from the last checkpoint.
            checkpoint_updated = await self._repository.checkpoint_updated_at(run_id)
            stale = self._seconds_since(checkpoint_updated)
            if stale is None or stale <= self._lifecycle.running_stale_seconds:
                raise AgentResumeRejected(
                    "RUN_IN_PROGRESS",
                    f"agent run {run_id} is still executing (checkpoint age: {stale})",
                )
        else:
            raise AgentResumeRejected(
                "RUN_TERMINAL", f"agent run {run_id} is {record.status}"
            )

        checkpoint = await self._repository.load_checkpoint(run_id)
        if checkpoint is None:
            raise AgentResumeRejected(
                "NO_CHECKPOINT", f"agent run {run_id} has no checkpoint"
            )

        initial_seq = await self._repository.count_steps(run_id)
        await self._repository.record_step(
            run_id=run_id,
            seq=initial_seq,
            kind="RESUME",
            tool=None,
            payload={"eventId": str(command.event_id)},
        )
        recorder = AgentRunRecorder(
            self._repository,
            run_id=run_id,
            command_event_id=str(command.event_id),
            trip_id=str(command.trip_id),
            initial_seq=initial_seq + 1,
        )
        await recorder.resume_existing()
        confirmed_preferences = await self._load_preferences(checkpoint.user_id)
        state = replace(
            checkpoint,
            user_message=command.payload.answer,
            pending_question=None,
            pending_options=None,
            pending_expected_type=None,
            pending_call=None,
            stop_reason=None,
            answer=None,
            # Ceilings are per dialog turn: a resumed turn gets a fresh step
            # budget and freezes the observation baseline it inherits.
            steps=0,
            turn_baseline_observations=len(checkpoint.observations),
            confirmed_preferences=confirmed_preferences,
        )
        result = await run_agent(
            self._loop_factory(),
            state,
            checkpoint_sink=self._dialog_sink(
                recorder, command, run_id, baseline_observations=len(state.observations)
            ),
        )
        question_published = await self._publish_question(result, run_id, command)
        completion_published = await self._publish_completion(result, run_id, command)
        if not question_published and not completion_published:
            await self._publish_run_finished(result, run_id, command)
        await recorder.finish(result)
        return result

    def _dialog_sink(
        self,
        recorder: AgentRunRecorder,
        command: AgentStartCommand | AgentResumeCommand,
        run_id: str,
        *,
        baseline_observations: int,
    ) -> Callable[[AgentState], Awaitable[None]]:
        """Wrap the recorder with restrained AGENT_STEP publishing.

        The streamed stream opens with the turn's input state, so ``cursor``
        starts at the observation baseline the turn inherited — only NEW tool
        observations become step events.  ``ask_user`` observations are
        excluded: the AGENT_ASK_USER event is their carrier, and a duplicate
        step would only add noise.  ``seq`` counts published steps within the
        turn, from zero.  Recorder checkpoints stay untouched.
        """
        cursor = baseline_observations
        turn_seq = 0

        async def sink(current: AgentState) -> None:
            nonlocal cursor, turn_seq
            await recorder.on_state(current)
            for observation in current.observations[cursor:]:
                cursor += 1
                if observation.tool == "ask_user":
                    continue
                await self._publisher(
                    AgentStepEvent(
                        event_type="AGENT_STEP",
                        schema_version=1,
                        event_id=uuid4(),
                        trace_id=command.trace_id,
                        trip_id=command.trip_id,
                        run_id=UUID(run_id),
                        occurred_at=datetime.now(UTC),
                        payload={
                            "seq": turn_seq,
                            "tool": observation.tool,
                            "ok": observation.ok,
                            "summary": observation.summary,
                            "error_code": observation.error_code,
                        },
                    )
                )
                turn_seq += 1
            cursor = max(cursor, len(current.observations))

        return sink

    @staticmethod
    def _seconds_since(timestamp: datetime | None) -> float | None:
        if timestamp is None:
            return None
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)
        return (datetime.now(UTC) - timestamp).total_seconds()

    async def _publish_question(
        self,
        result: AgentRunResult,
        run_id: str,
        command: AgentStartCommand | AgentResumeCommand,
    ) -> bool:
        if result.stop_reason != "WAITING_USER" or result.pending_question is None:
            if result.stop_reason == "WAITING_USER":
                logger.warning(
                    "run %s stopped in WAITING_USER without a pending question",
                    run_id,
                )
            return False
        event = AgentAskUserEvent(
            event_type="AGENT_ASK_USER",
            schema_version=1,
            event_id=uuid4(),
            trace_id=command.trace_id,
            trip_id=command.trip_id,
            run_id=UUID(run_id),
            occurred_at=datetime.now(UTC),
            payload={
                "question": result.pending_question,
                "options": (
                    list(result.pending_options) if result.pending_options else None
                ),
                "expected_type": _WIRE_EXPECTED_TYPES.get(
                    result.pending_expected_type or ""
                ),
            },
        )
        await self._publisher(event)
        return True

    async def _publish_completion(
        self,
        result: AgentRunResult,
        run_id: str,
        command: AgentStartCommand | AgentResumeCommand,
    ) -> bool:
        if result.stop_reason != "EMITTED" or result.itinerary is None:
            return False
        event = AgentCompletedEvent(
            event_type="AGENT_COMPLETED",
            schema_version=1,
            event_id=uuid4(),
            trace_id=command.trace_id,
            trip_id=command.trip_id,
            run_id=UUID(run_id),
            occurred_at=datetime.now(UTC),
            payload={
                "summary": f"行程已生成：{result.itinerary.get('title', '未命名')}",
                "itinerary": Itinerary.model_validate(result.itinerary),
                # Confirmed-slot projection (P2.8b apply flow): the frontend
                # writes these onto the trip and triggers the pipeline.
                "slots": {
                    name: {"value": slot.value, "state": slot.state.value}
                    for name, slot in result.slots.slots.items()
                    if slot.value is not None
                },
            },
        )
        await self._publisher(event)
        return True

    async def _publish_run_finished(
        self,
        result: AgentRunResult,
        run_id: str,
        command: AgentStartCommand | AgentResumeCommand,
    ) -> bool:
        stop = result.stop_reason
        if stop == "ANSWERED":
            status, reason = "ANSWERED", "ANSWERED"
            message = result.answer or _ANSWER_DEFAULT_MESSAGE
        elif stop == "CEILING_REACHED":
            status, reason = "STOPPED", stop
            message = _STOP_MESSAGES[stop]
        elif stop is None or stop in ("WAITING_USER", "EMITTED"):
            return False
        else:
            status, reason = "STOPPED", stop
            message = _STOP_DEFAULT_MESSAGE
        await self._publish_finished(
            command=command,
            run_id=run_id,
            status=status,
            reason_code=reason,
            message=message,
        )
        return True

    async def publish_resume_rejected(
        self, command: AgentResumeCommand, reason: str
    ) -> None:
        """Announce a rejected resume before the command dead-letters (P0).

        Without this the user's answer would vanish silently — the run was
        expired, already running, or already terminal.
        """
        await self._publish_finished(
            command=command,
            run_id=str(command.run_id),
            status="EXPIRED" if reason == "RUN_EXPIRED" else "STOPPED",
            reason_code=reason,
            message=_RESUME_REJECTION_MESSAGES.get(reason, _STOP_DEFAULT_MESSAGE),
        )

    async def _publish_finished(
        self,
        *,
        command: AgentStartCommand | AgentResumeCommand,
        run_id: str,
        status: str,
        reason_code: str,
        message: str,
    ) -> None:
        event = AgentRunFinishedEvent(
            event_type="AGENT_RUN_FINISHED",
            schema_version=1,
            event_id=uuid4(),
            trace_id=command.trace_id,
            trip_id=command.trip_id,
            run_id=UUID(run_id),
            occurred_at=datetime.now(UTC),
            payload={"status": status, "reason_code": reason_code, "message": message},
        )
        await self._publisher(event)


class AgentEventPublisher:
    """Publishes agent dialog events onto the event exchange."""

    def __init__(self, exchange: DialogEventExchange) -> None:
        self._exchange = exchange

    async def __call__(self, event: DialogEvent) -> None:
        outgoing = aio_pika.Message(
            body=event.model_dump_json(by_alias=True, exclude_none=True).encode("utf-8"),
            content_type="application/json",
            content_encoding="utf-8",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            message_id=str(event.event_id),
            correlation_id=str(event.trace_id),
            type=event.event_type,
            headers={
                "traceId": str(event.trace_id),
                "tripId": str(event.trip_id),
                "runId": str(event.run_id),
            },
        )
        await self._exchange.publish(
            outgoing,
            routing_key=_EVENT_ROUTING_KEYS[event.event_type],
            mandatory=True,
        )


async def handle_agent_delivery(
    message: Any,
    event_exchange: DialogEventExchange,
    processor: AgentDialogProcessor | None = None,
) -> None:
    """Consume one agent dialog command; never touches the planning chain."""
    try:
        raw_command: Any = json.loads(message.body)
        if not isinstance(raw_command, dict):
            raise ValueError("agent command must be a JSON object")
        event_type = raw_command.get("eventType")
        if event_type == "AGENT_START":
            command: AgentStartCommand | AgentResumeCommand = (
                AgentStartCommand.model_validate(raw_command)
            )
        elif event_type == "AGENT_RESUME":
            command = AgentResumeCommand.model_validate(raw_command)
        else:
            raise ValueError(f"unsupported agent command: {event_type!r}")
    except (ValueError, TypeError) as exception:
        # pydantic ValidationError is a ValueError; JSONDecodeError too.
        logger.warning("rejecting invalid agent command: %s", exception)
        await message.reject(requeue=False)
        return

    if processor is None:
        processor = await _default_agent_processor(event_exchange)
    try:
        if isinstance(command, AgentStartCommand):
            await processor.handle_start(command)
        else:
            await processor.handle_resume(command)
    except AgentResumeRejected as exception:
        logger.warning("rejecting agent resume: %s", exception)
        try:
            # The user's answer must not vanish silently: announce the
            # terminal on the wire before the command dead-letters.
            await processor.publish_resume_rejected(command, exception.reason)
        except Exception:  # noqa: BLE001 - the reject below must still happen
            logger.exception("publishing run-finished for rejected resume failed")
        await message.reject(requeue=False)
        return
    await message.ack()


_REAL_BACKEND_CACHE: dict[str, RealItineraryBuilder] = {}


def _itinerary_builder_for_mode() -> RealItineraryBuilder | DemoItineraryBuilder:
    """V3 C-1: choose the itinerary backend by the same provider mode the
    worker uses.  DEMO mode (or missing configuration) keeps the demo
    builder; a misconfigured real mode degrades to demo with a warning
    instead of taking the dialog feature down."""
    # Deferred: worker.amqp imports this module at load time.
    from trip_agent.providers.errors import ProviderExecutionMode
    from trip_agent.worker.amqp import WorkerSettings, build_planning_provider

    settings = WorkerSettings()
    if settings.resolved_provider_mode == ProviderExecutionMode.DEMO_ONLY:
        return DemoItineraryBuilder()
    cached = _REAL_BACKEND_CACHE.get("builder")
    if cached is not None:
        return cached
    try:
        import httpx

        provider = build_planning_provider(
            settings, http_client=httpx.AsyncClient(timeout=30)
        )
    except ValueError as error:
        logger.warning("agent itinerary real backend unavailable: %s", error)
        return DemoItineraryBuilder()
    builder = RealItineraryBuilder(provider=provider, provider_name="AMAP")
    _REAL_BACKEND_CACHE["builder"] = builder
    return builder


async def _default_agent_processor(event_exchange: DialogEventExchange) -> AgentDialogProcessor:
    # The agent tables share the knowledge database's `agent` schema.
    from trip_agent.acquisition.cli import AcquisitionSettings

    database_url = AcquisitionSettings().database_url()
    repository = PsycopgAgentRunRepository(database_url)
    profile_store = TravelProfileRepository(database_url)
    # Idempotent, checksummed — covers V1 (runs) and V2 (profile).
    await repository.migrate()
    # V3 C-2: the four observation tools are wired from the same provider
    # stack (per-capability degradation, fail closed).
    capabilities = build_observation_capabilities()
    registry = ToolRegistry.with_runtime(
        ToolRuntime(
            place_search=capabilities.place_search,
            route=capabilities.route,
            opening_hours=capabilities.opening_hours,
            knowledge=capabilities.knowledge,
            # V3 C-1: real planning backend per PROVIDER_MODE — the dialog
            # agent drafts REAL itineraries when planning is configured;
            # DEMO mode (or missing configuration) keeps the demo builder.
            itinerary_builder=_itinerary_builder_for_mode(),
            feasibility=StructuralFeasibilityGate(),
            profile_store=profile_store,
        )
    )
    return AgentDialogProcessor(
        repository=repository,
        publisher=AgentEventPublisher(event_exchange),
        loop_factory=lambda: AgentLoop(
            decider=build_decision_maker(tools=registry), tools=registry
        ),
        profile_store=profile_store,
    )
