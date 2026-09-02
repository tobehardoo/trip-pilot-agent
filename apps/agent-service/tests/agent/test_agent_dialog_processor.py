"""P2.1: the agent dialog path — start/resume commands drive bounded runs.

The conversation E2E uses a scripted deterministic decider over a fake
repository, so the full three-turn flow (ask → resume → ask → resume →
answer) proves checkpoint restoration, user-message injection, event shape,
trajectory continuation and command idempotency without a database.  The
AMQP dispatch tests reuse the fake delivery primitive shapes from
``test_amqp_worker`` (copied locally: the tests root is not on sys.path) and
assert agent commands never touch the planning chain.  Async flows run
through ``run_async`` — the project has no pytest-asyncio plugin.
"""

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from trip_agent.agent import (
    AgentLoop,
    AgentRunStarted,
    AgentState,
    Decision,
    SlotState,
    ToolCall,
    ToolRegistry,
    ToolRuntime,
)
from trip_agent.platform_util import run_async
from trip_agent.worker.agent_processor import (
    AGENT_ASK_USER_ROUTING_KEY,
    AGENT_COMPLETED_ROUTING_KEY,
    AGENT_RUN_FINISHED_ROUTING_KEY,
    AGENT_STEP_ROUTING_KEY,
    AgentDialogProcessor,
    AgentEventPublisher,
    AgentResumeRejected,
    AgentRunLifecycleConfig,
    handle_agent_delivery,
)
from trip_agent.worker.contracts import (
    AgentAskUserEvent,
    AgentCompletedEvent,
    AgentResumeCommand,
    AgentRunFinishedEvent,
    AgentStartCommand,
    AgentStepEvent,
    Itinerary,
    ItineraryActivity,
    ItineraryDay,
)

START_FIXTURE = (
    Path(__file__).resolve().parents[4]
    / "contracts"
    / "fixtures"
    / "agent-start-command-v1"
    / "valid.json"
)


# ── fake delivery primitives (mirror test_amqp_worker) ──────────────


@dataclass
class FakeIncomingMessage:
    body: bytes
    acked: bool = False
    rejected_with: bool | None = None

    async def ack(self) -> None:
        self.acked = True

    async def reject(self, *, requeue: bool) -> None:
        self.rejected_with = requeue


@dataclass
class FakeExchange:
    published: list[tuple[Any, str, bool]]

    def __init__(self) -> None:
        self.published = []

    async def publish(
        self, message: Any, *, routing_key: str, mandatory: bool = True
    ) -> None:
        self.published.append((message, routing_key, mandatory))


# ── scripted deterministic conversation ─────────────────────────────


class _TurnTakingDecider:
    """Ask city, ask dates, then build → gate the draft (auto-emit)."""

    async def decide(self, state: AgentState) -> Decision:
        destination = state.slots.get("destination")
        start_date = state.slots.get("start_date")
        if destination.hard and start_date.hard:
            if state.candidate_itinerary is None:
                return Decision(thought="build the draft", call=ToolCall("build_itinerary"))
            validated = any(
                obs.tool == "validate_itinerary" and obs.ok
                for obs in state.observations
            )
            if not validated:
                return Decision(
                    thought="gate the draft", call=ToolCall("validate_itinerary")
                )
            return Decision(thought="done", answer="好的，需求齐了。")
        if not destination.hard:
            if state.user_message and "成都" in state.user_message:
                return Decision(
                    thought="the answer names the destination",
                    call=ToolCall(
                        "update_constraints",
                        {"values": {"destination": "成都"}, "evidence": state.user_message},
                    ),
                )
            return Decision(
                thought="destination is unknown",
                call=ToolCall(
                    "ask_user",
                    {
                        "question": "你想去哪个城市？",
                        "options": ["成都", "北京"],
                        "expected_type": "choice",
                    },
                ),
            )
        if state.user_message and "10月1日" in state.user_message:
            return Decision(
                thought="the answer names the dates",
                call=ToolCall(
                    "update_constraints",
                    {
                        "values": {"start_date": "10月1日", "end_date": "10月3日"},
                        "evidence": state.user_message,
                    },
                ),
            )
        return Decision(
            thought="dates are unknown",
            call=ToolCall(
                "ask_user", {"question": "行程从哪天开始？", "expected_type": "text"}
            ),
        )


class FakeRepository:
    def __init__(self) -> None:
        self.steps: list[dict[str, Any]] = []
        self.checkpoints: dict[str, AgentState] = {}
        self.checkpoint_times: dict[str, datetime] = {}
        self.runs: dict[str, dict[str, Any]] = {}
        self.existing: dict[str, str] = {}

    async def start_run(
        self, *, run_id: str, command_event_id: str | None, trip_id: str | None
    ) -> AgentRunStarted:
        if command_event_id and command_event_id in self.existing:
            return AgentRunStarted(run_id=self.existing[command_event_id], created=False)
        if command_event_id:
            self.existing[command_event_id] = run_id
        self.runs[run_id] = {"status": "RUNNING", "updated_at": datetime.now(UTC)}
        return AgentRunStarted(run_id=run_id, created=True)

    async def record_step(
        self, *, run_id: str, seq: int, kind: str, tool: str | None, payload: dict[str, Any]
    ) -> None:
        self.steps.append({"run_id": run_id, "seq": seq, "kind": kind, "tool": tool})

    async def save_checkpoint(self, *, run_id: str, state: AgentState) -> None:
        self.checkpoints[run_id] = state
        self.checkpoint_times[run_id] = datetime.now(UTC)

    async def load_checkpoint(self, run_id: str) -> AgentState | None:
        return self.checkpoints.get(run_id)

    async def checkpoint_updated_at(self, run_id: str) -> datetime | None:
        return self.checkpoint_times.get(run_id)

    async def finish_run(self, *, run_id: str, status: str, **_kwargs: Any) -> None:
        self.runs[run_id]["status"] = status
        self.runs[run_id]["updated_at"] = datetime.now(UTC)

    async def load_run(self, run_id: str) -> Any:
        run = self.runs.get(run_id)
        if run is None:
            return None
        return SimpleNamespace(status=run["status"], updated_at=run["updated_at"])

    async def count_steps(self, run_id: str) -> int:
        return len([step for step in self.steps if step["run_id"] == run_id])


def _loop_factory() -> AgentLoop:
    async def builder(*, slots: Any, trip_id: str | None = None) -> Any:
        del slots, trip_id
        start = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
        return Itinerary(
            title="测试行程",
            days=(
                ItineraryDay(
                    date=start.date(),
                    activities=(
                        ItineraryActivity(
                            title="武侯祠",
                            startTime=start,
                            endTime=start.replace(hour=11),
                            estimatedCost=Decimal("0"),
                            source="DEMO",
                        ),
                    ),
                    transitLegs=(),
                ),
            ),
            estimatedTotalCost=Decimal("0"),
        )

    async def gate(**_kwargs: Any) -> Any:
        return SimpleNamespace(has_blocker=False)

    return AgentLoop(
        decider=_TurnTakingDecider(),
        tools=ToolRegistry.with_runtime(
            ToolRuntime(itinerary_builder=builder, feasibility=gate)
        ),
    )


class RecordingProcessor(AgentDialogProcessor):
    """Processor over the fake repository with a recorded event log."""

    def __init__(
        self, lifecycle: AgentRunLifecycleConfig | None = None
    ) -> None:
        self.repository = FakeRepository()
        self.published: list[
            AgentAskUserEvent | AgentStepEvent | AgentCompletedEvent | AgentRunFinishedEvent
        ] = []
        super().__init__(
            repository=self.repository,
            publisher=self._record,
            loop_factory=_loop_factory,
            lifecycle=lifecycle,
        )

    async def _record(
        self,
        event: AgentAskUserEvent | AgentStepEvent | AgentCompletedEvent | AgentRunFinishedEvent,
    ) -> None:
        self.published.append(event)


def _start_command(message: str) -> AgentStartCommand:
    # InboundMessageModel only validates by alias, so construction uses the
    # camelCase wire names directly.
    return AgentStartCommand(
        eventType="AGENT_START",
        schemaVersion=1,
        eventId=uuid4(),
        traceId=uuid4(),
        tripId=uuid4(),
        occurredAt=datetime.now(UTC),
        payload={"message": message},
    )


def _resume_command(run_id: str, answer: str) -> AgentResumeCommand:
    return AgentResumeCommand(
        eventType="AGENT_RESUME",
        schemaVersion=1,
        eventId=uuid4(),
        traceId=uuid4(),
        tripId=uuid4(),
        runId=UUID(run_id),
        occurredAt=datetime.now(UTC),
        payload={"answer": answer},
    )


async def _started_run() -> tuple[RecordingProcessor, str]:
    processor = RecordingProcessor()
    result = await processor.handle_start(_start_command("十一想去玩"))
    assert result is not None and result.stop_reason == "WAITING_USER"
    [run_id] = processor.repository.checkpoints
    return processor, run_id


# ── contract shape ──────────────────────────────────────────────────


def test_start_command_fixture_matches_the_model() -> None:
    wire = json.loads(START_FIXTURE.read_text(encoding="utf-8"))
    command = AgentStartCommand.model_validate(wire)
    assert command.payload.message == "十一想去成都玩，预算大概五千"
    wire["payload"]["runId"] = "5a1b2c3d-4e5f-4a6b-8c9d-0e1f2a3b4c5d"
    with pytest.raises(ValidationError):
        AgentStartCommand.model_validate(wire)


# ── the three-turn conversation ─────────────────────────────────────


def test_three_turn_conversation_completes_through_checkpoints() -> None:
    async def scenario() -> None:
        processor = RecordingProcessor()

        # Turn 1: the opening message cannot fill any required slot → ask city.
        # The ask_user tool observation is NOT a step event — the question
        # event is its carrier (restrained trace).
        first = await processor.handle_start(_start_command("十一想去玩"))
        assert first is not None and first.stop_reason == "WAITING_USER"
        [run_id] = processor.repository.checkpoints
        [first_question] = processor.published
        assert isinstance(first_question, AgentAskUserEvent)
        assert first_question.payload.question == "你想去哪个城市？"
        assert first_question.payload.options == ("成都", "北京")
        assert first_question.payload.expected_type == "CHOICE"
        assert first_question.run_id == UUID(run_id)
        assert processor.repository.runs[run_id]["status"] == "WAITING_USER"

        # Turn 2: the answer becomes evidence; the destination confirms, dates ask.
        second = await processor.handle_resume(_resume_command(run_id, "就去成都"))
        assert second.stop_reason == "WAITING_USER"
        assert len(processor.published) == 3
        second_step, second_question = processor.published[1], processor.published[2]
        assert isinstance(second_step, AgentStepEvent)
        assert second_step.payload.tool == "update_constraints" and second_step.payload.seq == 0
        assert isinstance(second_question, AgentAskUserEvent)
        assert second_question.payload.question == "行程从哪天开始？"
        assert second_question.payload.expected_type == "TEXT"

        # Turn 3: dates confirm → build → gate passes → deterministic emit.
        third = await processor.handle_resume(
            _resume_command(run_id, "10月1日到10月3日出发")
        )
        assert third.stop_reason == "EMITTED"
        assert third.itinerary is not None
        assert third.itinerary["title"] == "测试行程"
        kinds = [type(event).__name__ for event in processor.published]
        assert kinds == [
            "AgentAskUserEvent",
            "AgentStepEvent",
            "AgentAskUserEvent",
            "AgentStepEvent",
            "AgentStepEvent",
            "AgentStepEvent",
            "AgentCompletedEvent",
        ]
        completed = processor.published[-1]
        assert isinstance(completed, AgentCompletedEvent)
        # AUDIT-01（归边 A）：completed 事件不再携带完整 itinerary，仅摘要 + 槽位。
        assert completed.payload.summary.startswith("行程已生成：")
        assert completed.payload.slots["destination"].value == "成都"
        assert processor.repository.runs[run_id]["status"] == "COMPLETED"
        assert third.slots.get("destination").state is SlotState.CONFIRMED
        assert third.slots.get("start_date").state is SlotState.CONFIRMED
        assert third.slots.get("end_date").state is SlotState.CONFIRMED
        assert third.slots.get("destination").verified_by == "rule:evidence-match"

    run_async(scenario())


def test_trajectory_steps_continue_across_resumes() -> None:
    async def scenario() -> None:
        processor, run_id = await _started_run()
        await processor.handle_resume(_resume_command(run_id, "就去成都"))
        seqs = [
            step["seq"]
            for step in processor.repository.steps
            if step["run_id"] == run_id
        ]
        assert seqs == sorted(seqs)
        assert len(seqs) == len(set(seqs)), "step sequence must stay unique"
        assert any(step["kind"] == "RESUME" for step in processor.repository.steps)

    run_async(scenario())


def test_duplicate_start_command_is_idempotent() -> None:
    async def scenario() -> None:
        processor = RecordingProcessor()
        command = _start_command("十一想去玩")
        assert await processor.handle_start(command) is not None
        published = len(processor.published)
        assert await processor.handle_start(command) is None
        assert len(processor.published) == published

    run_async(scenario())


def test_resume_of_unknown_run_is_rejected() -> None:
    async def scenario() -> None:
        processor = RecordingProcessor()
        with pytest.raises(AgentResumeRejected):
            await processor.handle_resume(_resume_command(str(uuid4()), "答案"))

    run_async(scenario())


def test_resume_of_completed_run_is_rejected() -> None:
    async def scenario() -> None:
        processor, run_id = await _started_run()
        processor.repository.runs[run_id]["status"] = "COMPLETED"
        with pytest.raises(AgentResumeRejected) as excinfo:
            await processor.handle_resume(_resume_command(run_id, "就去成都"))
        assert excinfo.value.reason == "RUN_TERMINAL"

    run_async(scenario())


# ── P3.1: resumability lifecycle ────────────────────────────────────


def _short_lifecycle() -> AgentRunLifecycleConfig:
    return AgentRunLifecycleConfig(waiting_ttl_seconds=3600, running_stale_seconds=600)


def test_expired_waiting_run_is_marked_and_rejected() -> None:
    async def scenario() -> None:
        processor = RecordingProcessor(lifecycle=_short_lifecycle())
        started = await processor.handle_start(_start_command("十一想去玩"))
        assert started is not None
        [run_id] = processor.repository.checkpoints
        published = len(processor.published)
        processor.repository.runs[run_id]["updated_at"] = datetime.now(UTC) - timedelta(
            seconds=7200
        )

        with pytest.raises(AgentResumeRejected) as excinfo:
            await processor.handle_resume(_resume_command(run_id, "就去成都"))

        assert excinfo.value.reason == "RUN_EXPIRED"
        assert processor.repository.runs[run_id]["status"] == "EXPIRED"
        assert len(processor.published) == published, "no turn may run for an expired run"

    run_async(scenario())


def test_fresh_waiting_run_still_resumes() -> None:
    async def scenario() -> None:
        processor = RecordingProcessor(lifecycle=_short_lifecycle())
        result = await processor.handle_start(_start_command("十一想去玩"))
        assert result is not None and result.stop_reason == "WAITING_USER"
        [run_id] = processor.repository.checkpoints
        resumed = await processor.handle_resume(_resume_command(run_id, "就去成都"))
        assert resumed.stop_reason == "WAITING_USER"

    run_async(scenario())


def test_stale_running_run_recovers_from_its_checkpoint() -> None:
    async def scenario() -> None:
        processor = RecordingProcessor(lifecycle=_short_lifecycle())
        started = await processor.handle_start(_start_command("十一想去玩"))
        assert started is not None
        [run_id] = processor.repository.checkpoints
        # Simulate a worker crash mid-turn: the run never reached a stop point
        # and its checkpoint stopped ticking long ago.
        processor.repository.runs[run_id]["status"] = "RUNNING"
        processor.repository.checkpoint_times[run_id] = datetime.now(UTC) - timedelta(
            seconds=1200
        )

        result = await processor.handle_resume(_resume_command(run_id, "就去成都"))

        assert result.stop_reason == "WAITING_USER"
        assert processor.repository.runs[run_id]["status"] == "WAITING_USER"

    run_async(scenario())


def test_fresh_running_run_is_refused_to_prevent_double_execution() -> None:
    async def scenario() -> None:
        processor = RecordingProcessor(lifecycle=_short_lifecycle())
        started = await processor.handle_start(_start_command("十一想去玩"))
        assert started is not None
        [run_id] = processor.repository.checkpoints
        processor.repository.runs[run_id]["status"] = "RUNNING"
        processor.repository.checkpoint_times[run_id] = datetime.now(UTC)

        with pytest.raises(AgentResumeRejected) as excinfo:
            await processor.handle_resume(_resume_command(run_id, "就去成都"))

        assert excinfo.value.reason == "RUN_IN_PROGRESS"

    run_async(scenario())


# ── AMQP dispatch ───────────────────────────────────────────────────


def test_valid_start_command_is_dispatched_and_acked() -> None:
    async def scenario() -> None:
        handled: list[Any] = []

        class _SpyProcessor:
            async def handle_start(self, command: AgentStartCommand) -> None:
                handled.append(command)

            async def handle_resume(self, command: AgentResumeCommand) -> None:
                handled.append(command)

        wire = _start_command("十一想去玩").model_dump(mode="json", by_alias=True)
        message = FakeIncomingMessage(body=json.dumps(wire).encode("utf-8"))
        exchange = FakeExchange()
        await handle_agent_delivery(message, exchange, processor=_SpyProcessor())
        assert message.acked and message.rejected_with is None
        assert len(handled) == 1 and handled[0].event_type == "AGENT_START"
        assert exchange.published == []

    run_async(scenario())


def test_invalid_agent_command_is_rejected_without_the_planning_chain() -> None:
    async def scenario() -> None:
        wire = _start_command("十一想去玩").model_dump(mode="json", by_alias=True)
        wire["schemaVersion"] = 2
        message = FakeIncomingMessage(body=json.dumps(wire).encode("utf-8"))
        exchange = FakeExchange()
        await handle_agent_delivery(message, exchange, processor=RecordingProcessor())
        assert message.rejected_with is False and not message.acked
        assert exchange.published == []

    run_async(scenario())


def test_unknown_agent_event_type_is_rejected() -> None:
    async def scenario() -> None:
        body = json.dumps({"eventType": "AGENT_PANIC", "schemaVersion": 1})
        message = FakeIncomingMessage(body=body.encode("utf-8"))
        await handle_agent_delivery(
            message, FakeExchange(), processor=RecordingProcessor()
        )
        assert message.rejected_with is False

    run_async(scenario())


def test_dialog_events_publish_on_their_agent_routes() -> None:
    async def scenario() -> None:
        exchange = FakeExchange()
        processor = AgentDialogProcessor(
            repository=FakeRepository(),
            publisher=AgentEventPublisher(exchange),
            loop_factory=_loop_factory,
        )
        await processor.handle_start(_start_command("十一想去玩"))
        routes = [routing_key for _, routing_key, _ in exchange.published]
        assert routes == [AGENT_ASK_USER_ROUTING_KEY]

    run_async(scenario())


def test_full_conversation_routes_reach_their_exchanges() -> None:
    async def scenario() -> None:
        exchange = FakeExchange()
        repository = FakeRepository()
        processor = AgentDialogProcessor(
            repository=repository,
            publisher=AgentEventPublisher(exchange),
            loop_factory=_loop_factory,
        )
        first = await processor.handle_start(_start_command("十一想去玩"))
        assert first is not None
        [run_id] = repository.checkpoints
        await processor.handle_resume(_resume_command(run_id, "就去成都"))
        await processor.handle_resume(_resume_command(run_id, "10月1日到10月3日出发"))

        routes = [routing_key for _, routing_key, _ in exchange.published]
        assert routes == [
            AGENT_ASK_USER_ROUTING_KEY,
            AGENT_STEP_ROUTING_KEY,
            AGENT_ASK_USER_ROUTING_KEY,
            AGENT_STEP_ROUTING_KEY,
            AGENT_STEP_ROUTING_KEY,
            AGENT_STEP_ROUTING_KEY,
            AGENT_COMPLETED_ROUTING_KEY,
        ]
        wires = [
            json.loads(outgoing.body.decode("utf-8"))
            for outgoing, _, _ in exchange.published
        ]
        assert wires[0]["payload"]["question"] == "你想去哪个城市？"
        # AUDIT-01（归边 A）防回归：序列化 wire 的 completed 事件绝不含 itinerary。
        assert wires[-1]["payload"]["summary"].startswith("行程已生成：")
        assert "itinerary" not in wires[-1]["payload"]

    run_async(scenario())


# ── AGENT_RUN_FINISHED: terminals the user must see (P0) ────────────


class _LoopingDecider:
    """Never converges — drives the loop into its step ceiling."""

    async def decide(self, state: AgentState) -> Decision:
        del state
        return Decision(
            thought="keep going",
            call=ToolCall("search_place", {"keyword": "景点"}),
        )


class _AnsweringDecider:
    """Answers in plain text instead of calling a tool."""

    async def decide(self, state: AgentState) -> Decision:
        del state
        return Decision(thought="just answer", answer="好的，我记下了。")


def _simple_loop(decider: Any) -> AgentLoop:
    return AgentLoop(
        decider=decider,
        tools=ToolRegistry.with_runtime(ToolRuntime()),
    )


def test_ceiling_stop_publishes_run_finished() -> None:
    async def scenario() -> None:
        processor = RecordingProcessor()
        processor._loop_factory = lambda: _simple_loop(_LoopingDecider())  # noqa: SLF001

        result = await processor.handle_start(_start_command("十一想去玩"))

        assert result is not None and result.stop_reason == "CEILING_REACHED"
        finished = processor.published[-1]
        assert isinstance(finished, AgentRunFinishedEvent)
        assert finished.payload.status == "STOPPED"
        assert finished.payload.reason_code == "CEILING_REACHED"
        assert "步骤上限" in finished.payload.message
        assert not any(
            isinstance(event, AgentAskUserEvent | AgentCompletedEvent)
            for event in processor.published
        )
        assert processor.repository.runs[finished.run_id.__str__()]["status"] == "STOPPED"

    run_async(scenario())


def test_plain_answer_publishes_run_finished_answered() -> None:
    async def scenario() -> None:
        processor = RecordingProcessor()
        processor._loop_factory = lambda: _simple_loop(_AnsweringDecider())  # noqa: SLF001

        result = await processor.handle_start(_start_command("你好呀"))

        assert result is not None and result.stop_reason == "ANSWERED"
        [finished] = processor.published
        assert isinstance(finished, AgentRunFinishedEvent)
        assert finished.payload.status == "ANSWERED"
        assert finished.payload.message == "好的，我记下了。"

    run_async(scenario())


def test_rejected_resume_announces_the_terminal_before_dead_lettering() -> None:
    async def scenario() -> None:
        processor = RecordingProcessor(lifecycle=_short_lifecycle())
        started = await processor.handle_start(_start_command("十一想去玩"))
        assert started is not None
        [run_id] = processor.repository.checkpoints
        processor.repository.runs[run_id]["updated_at"] = datetime.now(UTC) - timedelta(
            seconds=7200
        )

        wire = _resume_command(run_id, "就去成都").model_dump(mode="json", by_alias=True)
        message = FakeIncomingMessage(body=json.dumps(wire).encode("utf-8"))
        await handle_agent_delivery(message, FakeExchange(), processor=processor)

        assert message.rejected_with is False and not message.acked
        [finished] = [
            event
            for event in processor.published
            if isinstance(event, AgentRunFinishedEvent)
        ]
        assert finished.payload.status == "EXPIRED"
        assert finished.payload.reason_code == "RUN_EXPIRED"
        assert finished.run_id == UUID(run_id)

    run_async(scenario())


def test_run_finished_publishes_on_its_agent_route() -> None:
    async def scenario() -> None:
        exchange = FakeExchange()
        repository = FakeRepository()
        processor = AgentDialogProcessor(
            repository=repository,
            publisher=AgentEventPublisher(exchange),
            loop_factory=lambda: _simple_loop(_LoopingDecider()),
        )
        await processor.handle_start(_start_command("十一想去玩"))
        routes = [routing_key for _, routing_key, _ in exchange.published]
        assert routes[-1] == AGENT_RUN_FINISHED_ROUTING_KEY

    run_async(scenario())
