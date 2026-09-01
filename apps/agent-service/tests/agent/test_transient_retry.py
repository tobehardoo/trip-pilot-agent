"""V3 D-2 — transient failure recovery: one bounded agent-level retry.

The provider layer already retries transient failures with backoff
(providers/retry.py) and arrives at the agent with a structured, exhausted
error (PlanningProviderError → tools.py boundary).  D-2 adds the ONE thing
the provider cannot do: a single agent-level second chance, decided by the
AskingDecider as a normal agent action (strategy RETRY) — never a loop.

Bounds (user §十/§十一):

- attempts <= 1 → retry the same build under the SAME confirmed constraints;
- attempts >= 2 → the existing WAITING_USER exit (no new terminal state);
  a reply to that notice is the user's consent to try again right now, so
  every rebuild past the bound is user-initiated;
- success resets the failure memory automatically (D-1 semantics).

Tests run the REAL chain: ToolObservation → _act_node → classify_failure →
AskingDecider → retry decision → build_itinerary (user §十七), plus the
processor/checkpoint level for persistence integrity (§二十四).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

from trip_agent.agent.graph import AgentLoop, AskingDecider, run_agent
from trip_agent.agent.state import (
    SLOT_NAMES,
    AgentState,
    ConstraintSlots,
    SlotState,
)
from trip_agent.agent.tools import ToolRegistry, ToolRuntime
from trip_agent.domain.planning.protocols import (
    OptimizationConflict,
    PlanningInfeasibleError,
)
from trip_agent.providers.errors import PlanningProviderError
from trip_agent.worker.agent_processor import AgentDialogProcessor
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

_START_MESSAGE = "想去成都玩 10月1日到10月3日，预算 2500"

# ── harness ──────────────────────────────────────────────────────────────────


def _itinerary() -> Itinerary:
    start = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
    return Itinerary(
        title="成都 行程",
        days=(
            ItineraryDay(
                date=start.date(),
                activities=(
                    ItineraryActivity(
                        title="宽窄巷子",
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


class _ScriptedBuilder:
    """Deterministic test double: fails with the scripted provider errors
    (in order), then succeeds.  With ``repeat_last=True`` the final error is
    raised forever (an outage that never heals)."""

    def __init__(self, *events: str | Exception, repeat_last: bool = False) -> None:
        self._events = list(events)
        self._repeat_last = repeat_last

    async def __call__(self, *, slots: Any, trip_id: str | None = None) -> Itinerary:
        if self._events:
            event = self._events.pop(0)
            if self._repeat_last and not self._events:
                self._events.append(event)
            if isinstance(event, Exception):
                raise event
            raise PlanningProviderError(event)
        return _itinerary()


def _counting(builder: Any) -> tuple[Any, list[int]]:
    """Wrap a builder so the test can assert exactly how often it ran."""
    calls: list[int] = []

    async def wrapper(*, slots: Any, trip_id: str | None = None) -> Any:
        calls.append(1)
        return await builder(slots=slots, trip_id=trip_id)

    wrapper.__name__ = "counting_builder"
    return wrapper, calls


def _confirmed_slots() -> ConstraintSlots:
    slots = ConstraintSlots.empty()
    for name, value in (
        ("destination", "成都"),
        # the raw message forms — the resume-time adjustment parser must see
        # them as UNCHANGED so the scripted failure branches are exercised
        ("start_date", "10月1日"),
        ("end_date", "10月3日"),
        ("budget", "2500"),
    ):
        slots = slots.fill(
            name,
            value,
            state=SlotState.CONFIRMED,
            evidence=value,
            verified_by="rule:evidence-match",
        )
    return slots


def _collector() -> tuple[list[AgentState], Any]:
    """Async checkpoint sink collecting every node snapshot."""
    states: list[AgentState] = []

    async def sink(state: AgentState) -> None:
        states.append(state)

    return states, sink


def _gate() -> Any:
    async def gate(**_kwargs: Any) -> Any:
        return SimpleNamespace(has_blocker=False)

    return gate


def _loop(builder: Any) -> AgentLoop:
    return AgentLoop(
        decider=AskingDecider(),
        tools=ToolRegistry.with_runtime(
            ToolRuntime(itinerary_builder=builder, feasibility=_gate())
        ),
    )


class _FakeRepository:
    def __init__(self) -> None:
        self.runs: dict[str, dict[str, Any]] = {}
        self.steps: list[dict[str, Any]] = []
        self.existing: dict[str, str] = {}
        self.checkpoints: dict[str, AgentState] = {}
        self.checkpoint_times: dict[str, datetime] = {}

    async def start_run(
        self,
        *,
        run_id: str,
        command_event_id: str | None = None,
        trip_id: str | None = None,
    ) -> Any:
        from trip_agent.agent.persistence import AgentRunStarted

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
        return (
            SimpleNamespace(status=run["status"], updated_at=run["updated_at"])
            if run
            else None
        )

    async def count_steps(self, run_id: str) -> int:
        return 0


class _RecordingProcessor(AgentDialogProcessor):
    """Processor over the fake repository with a recorded event log and the
    production AskingDecider."""

    def __init__(self, *, builder: Any) -> None:
        self.repository = _FakeRepository()
        self.published: list[
            AgentAskUserEvent | AgentStepEvent | AgentCompletedEvent | AgentRunFinishedEvent
        ] = []
        super().__init__(
            repository=self.repository,
            publisher=self._record,
            loop_factory=lambda: _loop(builder),
        )

    async def _record(self, event: object) -> None:
        self.published.append(event)


def _start_command(message: str) -> AgentStartCommand:
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


def _asks(processor: _RecordingProcessor) -> list[AgentAskUserEvent]:
    return [e for e in processor.published if isinstance(e, AgentAskUserEvent)]


def _builds(state: AgentState) -> list[Any]:
    return [obs for obs in state.observations if obs.tool == "build_itinerary"]


# ── Test A: transient once → retry → EMITTED ────────────────────────────────


def test_transient_failure_retries_once_then_emits() -> None:
    builder, calls = _counting(_ScriptedBuilder("PROVIDER_TIMEOUT"))
    states, sink = _collector()
    result = asyncio.run(
        run_agent(
            _loop(builder),
            AgentState(slots=_confirmed_slots(), user_message=_START_MESSAGE),
            checkpoint_sink=sink,
        )
    )

    assert result.stop_reason == "EMITTED"
    assert len(calls) == 2, "exactly one agent-level retry"
    builds = [obs for obs in result.observations if obs.tool == "build_itinerary"]
    assert [obs.ok for obs in builds] == [False, True]
    assert builds[0].error_code == "PROVIDER_TIMEOUT"

    # the retry was a declared, observable decision (user §二十七)
    build_decisions = [
        s
        for s in states
        if s.pending_call is not None and s.pending_call.tool == "build_itinerary"
    ]
    assert [s.strategy for s in build_decisions] == ["DIRECT", "RETRY"]

    # failure memory: TRANSIENT #1 after the first failure, cleared on success
    assert max(s.failure_attempts for s in states) == 1, "no double increment"
    assert any(
        s.failure_kind == "TRANSIENT"
        and s.failure_signature == "TRANSIENT:build_itinerary:PROVIDER_TIMEOUT"
        for s in states
    )
    final = states[-1]
    assert final.failure_kind is None
    assert final.failure_signature is None
    assert final.failure_attempts == 0


# ── Test D (loop level): retry preserves the confirmed slots exactly ────────


def test_retry_preserves_the_confirmed_slots_exactly() -> None:
    states, sink = _collector()
    asyncio.run(
        run_agent(
            _loop(_ScriptedBuilder("PROVIDER_TIMEOUT")),
            AgentState(slots=_confirmed_slots(), user_message=_START_MESSAGE),
            checkpoint_sink=sink,
        )
    )
    before = next(
        s
        for s in states
        if s.pending_call is not None and s.pending_call.tool == "build_itinerary"
    )
    after = states[-1]
    assert after.slots == before.slots, "the retry must not touch any slot"


# ── Test C: transient retries, a deterministic failure does not ─────────────


def test_transient_retries_but_deterministic_failure_does_not() -> None:
    transient_builder, transient_calls = _counting(_ScriptedBuilder("PROVIDER_UNAVAILABLE"))
    transient = asyncio.run(
        run_agent(
            _loop(transient_builder),
            AgentState(slots=_confirmed_slots(), user_message=_START_MESSAGE),
        )
    )

    infeasible_builder, infeasible_calls = _counting(
        _ScriptedBuilder(
            PlanningInfeasibleError(
                conflicts=(
                    OptimizationConflict(
                        "MUST_VISIT_UNAVAILABLE",
                        "所选必去地点不是可安排的景点",
                        ("must-visit",),
                    ),
                ),
                relaxations=(),
            )
        )
    )
    deterministic = asyncio.run(
        run_agent(
            _loop(infeasible_builder),
            AgentState(slots=_confirmed_slots(), user_message=_START_MESSAGE),
        )
    )

    assert len(transient_calls) == 2, "transient → one retry"
    assert transient.stop_reason == "EMITTED"
    assert len(infeasible_calls) == 1, "USER_CONSTRAINT → the user, not a retry"
    assert deterministic.stop_reason == "WAITING_USER"
    assert len(transient_calls) != len(infeasible_calls)


# ── Test B: persistent transient failure is bounded (processor level) ───────


def test_persistent_transient_failure_is_bounded_and_exits_to_the_user() -> None:
    builder, calls = _counting(_ScriptedBuilder("PROVIDER_TIMEOUT", repeat_last=True))
    processor = _RecordingProcessor(builder=builder)
    asyncio.run(processor.handle_start(_start_command(_START_MESSAGE)))
    run_id = next(iter(processor.repository.runs))

    # first run: first attempt + exactly one bounded retry → the user exit
    assert processor.repository.runs[run_id]["status"] == "WAITING_USER"
    checkpoint = processor.repository.checkpoints[run_id]
    assert len(_builds(checkpoint)) == 2, "never rebuilds to the step ceiling"
    assert checkpoint.failure_kind == "TRANSIENT"
    assert checkpoint.failure_signature == "TRANSIENT:build_itinerary:PROVIDER_TIMEOUT"
    assert checkpoint.failure_attempts == 2, "each build classified exactly once"
    assert not any(
        isinstance(e, AgentCompletedEvent) for e in processor.published
    ), "a broken provider must not emit a plan"

    ask = _asks(processor)[0]
    assert "PROVIDER_TIMEOUT" in ask.payload.question
    assert "已自动重试" in ask.payload.question

    # resume: the reply is the user's consent — ONE more build, then the exit
    # repeats.  failure_attempts continues (2 → 3): a checkpoint must neither
    # reset nor double-increment it (user §二十四).
    asyncio.run(processor.handle_resume(_resume_command(run_id, "再试一次")))

    assert processor.repository.runs[run_id]["status"] == "WAITING_USER"
    resumed = processor.repository.checkpoints[run_id]
    assert len(_builds(resumed)) == 3, "the user-authorized attempt ran once"
    assert resumed.failure_attempts == 3
    assert resumed.failure_kind == "TRANSIENT"
    assert len(_asks(processor)) == 2
    assert len(calls) == 3


def test_quota_exhaustion_is_bounded_the_same_way() -> None:
    """§二十六: QUOTA_EXCEEDED was classified TRANSIENT by D-1; the unified
    one-shot retry applies, and the test proves it cannot form a loop —
    the second failure exits to the user instead of rebuilding on."""
    builder, calls = _counting(
        _ScriptedBuilder("PROVIDER_QUOTA_EXHAUSTED", repeat_last=True)
    )
    processor = _RecordingProcessor(builder=builder)
    asyncio.run(processor.handle_start(_start_command(_START_MESSAGE)))
    run_id = next(iter(processor.repository.runs))

    assert processor.repository.runs[run_id]["status"] == "WAITING_USER"
    checkpoint = processor.repository.checkpoints[run_id]
    assert len(_builds(checkpoint)) == 2
    assert len(calls) == 2
    assert checkpoint.failure_attempts == 2


# ── Test D (processor level): retry never touches the user constraints ──────


def test_retry_never_touches_the_user_constraints() -> None:
    processor = _RecordingProcessor(builder=_ScriptedBuilder("PROVIDER_TIMEOUT"))
    asyncio.run(processor.handle_start(_start_command(_START_MESSAGE)))
    run_id = next(iter(processor.repository.runs))

    final = processor.repository.checkpoints[run_id]
    assert final.slots.confirmed_values() == {
        "destination": "成都",
        "start_date": "10月1日",
        "end_date": "10月3日",
        "budget": "2500",
    }
    assert final.slots.rejected_values() == {}
    assert all(
        final.slots.get(name).state is not SlotState.USER_OVERRIDE for name in SLOT_NAMES
    )
    # the agent never invents constraint values to escape a transient blip
    assert final.slots.get("must_visit").value is None
    assert final.slots.get("fixed_schedules").value is None
    assert final.slots.get("budget").value == "2500"


# ── Test E: success clears the failure memory in the real checkpoint ────────


def test_successful_retry_clears_failure_memory_in_the_checkpoint() -> None:
    processor = _RecordingProcessor(builder=_ScriptedBuilder("PROVIDER_TIMEOUT"))
    asyncio.run(processor.handle_start(_start_command(_START_MESSAGE)))
    run_id = next(iter(processor.repository.runs))

    assert processor.repository.runs[run_id]["status"] == "COMPLETED"
    final = processor.repository.checkpoints[run_id]
    assert len(_builds(final)) == 2
    assert final.failure_kind is None
    assert final.failure_signature is None
    assert final.failure_attempts == 0, "no EMITTED with a stale TRANSIENT memory"
    completed = [e for e in processor.published if isinstance(e, AgentCompletedEvent)]
    assert completed and completed[0].payload.itinerary is not None


# ── Test F: a changed failure kind takes over the decision ──────────────────


def test_retry_stops_when_the_failure_kind_changes() -> None:
    """TRANSIENT #1 → retry → the retry fails as a USER_CONSTRAINT refusal:
    exactly one retry happened, then the EXISTING infeasibility ask_user
    takes over — the stale TRANSIENT memory must not trigger a third build."""
    builder, calls = _counting(
        _ScriptedBuilder(
            "PROVIDER_TIMEOUT",
            PlanningInfeasibleError(
                conflicts=(
                    OptimizationConflict(
                        "MUST_VISIT_UNAVAILABLE",
                        "所选必去地点不是可安排的景点",
                        ("must-visit",),
                    ),
                ),
                relaxations=(),
            ),
        )
    )
    processor = _RecordingProcessor(builder=builder)
    asyncio.run(processor.handle_start(_start_command(_START_MESSAGE)))
    run_id = next(iter(processor.repository.runs))

    assert processor.repository.runs[run_id]["status"] == "WAITING_USER"
    assert len(calls) == 2, "retry happened exactly once"
    final = processor.repository.checkpoints[run_id]
    assert final.failure_kind == "USER_CONSTRAINT"
    assert final.failure_signature == "USER_CONSTRAINT:build_itinerary:MUST_VISIT_UNAVAILABLE"
    assert final.failure_attempts == 1, "the new kind starts a fresh count"
    ask = _asks(processor)[-1]
    assert "无法在当前约束下生成" in ask.payload.question
    assert "暂时不可用" not in ask.payload.question, "the notice is the transient exit"
