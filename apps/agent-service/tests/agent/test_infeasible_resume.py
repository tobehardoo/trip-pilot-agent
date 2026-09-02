"""V3 D-3 — the infeasible ask_user → resume loop closes.

P0 fix (D-0 audit §05): after an infeasible build the resume reply was
never parsed into a constraint update — required_hard kept the message
parser unreachable and the same question repeated until the TTL.

Now the AskingDecider parses the reply FIRST (values/rejections from the
user's own words; the evidence gate still decides downstream) and only
re-asks when the reply carries no recognizable adjustment.  A confirmed
adjustment clears the stale candidate and the failure context, so the
loop REBUILDS instead of re-asking (Test E).  The agent never mutates
constraints on its own — every change traces back to the user's words.
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
    AgentState,
    ConstraintSlots,
    SlotState,
)
from trip_agent.agent.tools import ToolRegistry, ToolRuntime
from trip_agent.domain.planning.protocols import (
    OptimizationConflict,
    PlanningInfeasibleError,
)
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

# ── harness ──────────────────────────────────────────────────────────────────


class _BudgetInfeasibleBuilder:
    """Deterministic test double: the plan is infeasible while the confirmed
    budget is below 3000 (the same refusal shape the demo provider raises
    for unverifiable must-visit places).  Raising the budget fixes it."""

    async def __call__(self, *, slots: Any, trip_id: str | None = None) -> Itinerary:
        values = slots.confirmed_values()
        budget = values.get("budget")
        if budget is not None and Decimal(str(budget)) < Decimal("3000"):
            raise PlanningInfeasibleError(
                conflicts=(
                    OptimizationConflict(
                        "MUST_VISIT_UNAVAILABLE",
                        "当前预算不足以支持必去地点的安排",
                        ("must-visit",),
                    ),
                ),
                relaxations=(),
            )
        return _itinerary()


class _MustVisitInfeasibleBuilder:
    """Deterministic test double: any confirmed must-visit is unverifiable
    (the demo provider semantics) — removing it fixes the plan."""

    async def __call__(self, *, slots: Any, trip_id: str | None = None) -> Itinerary:
        if slots.confirmed_values().get("must_visit"):
            raise PlanningInfeasibleError(
                conflicts=(
                    OptimizationConflict(
                        "MUST_VISIT_UNAVAILABLE",
                        "所选必去地点不是可安排的景点",
                        ("must-visit",),
                    ),
                ),
                relaxations=(),
            )
        return _itinerary()


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


async def _gate(**_kwargs: Any) -> Any:
    return SimpleNamespace(has_blocker=False)


class _FakeRepository:
    def __init__(self) -> None:
        self.runs: dict[str, dict[str, Any]] = {}
        self.steps: list[dict[str, Any]] = []
        self.existing: dict[str, str] = {}
        self.checkpoints: dict[str, AgentState] = {}
        self.checkpoint_times: dict[str, datetime] = {}

    async def start_run(
        self, *, run_id: str, command_event_id: str | None = None, trip_id: str | None = None
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
        return SimpleNamespace(status=run["status"], updated_at=run["updated_at"]) if run else None

    async def count_steps(self, run_id: str) -> int:
        return 0


class _RecordingProcessor(AgentDialogProcessor):
    """Processor over the fake repository with a recorded event log and the
    production AskingDecider."""

    def __init__(self, *, builder: object) -> None:
        self.repository = _FakeRepository()
        self.published: list[
            AgentAskUserEvent | AgentStepEvent | AgentCompletedEvent | AgentRunFinishedEvent
        ] = []
        super().__init__(
            repository=self.repository,
            publisher=self._record,
            loop_factory=lambda: AgentLoop(
                decider=AskingDecider(),
                tools=ToolRegistry.with_runtime(
                    ToolRuntime(
                        itinerary_builder=builder,
                        feasibility=asyncio_lambda_gate(),
                    )
                ),
            ),
        )

    async def _record(self, event: object) -> None:
        self.published.append(event)


def asyncio_lambda_gate():
    async def gate(**_kwargs: Any) -> Any:
        return SimpleNamespace(has_blocker=False)

    return gate


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


# ── Test B: budget raise → update → replan → EMITTED ─────────────────────────


def test_budget_adjustment_resume_replans_and_emits() -> None:
    processor = _RecordingProcessor(builder=_BudgetInfeasibleBuilder())
    run_id = next(iter({})) if False else None
    asyncio.run(processor.handle_start(_start_command("想去成都玩 10月1日到10月3日，预算 2500")))
    run_id = next(iter(processor.repository.runs))

    # first run: deterministic infeasible → the conflict is asked, not hidden
    assert processor.repository.runs[run_id]["status"] == "WAITING_USER"
    checkpoint = processor.repository.checkpoints[run_id]
    assert checkpoint.failure_kind == "USER_CONSTRAINT"
    assert checkpoint.failure_attempts == 1
    assert checkpoint.candidate_itinerary is None
    assert len(_asks(processor)) == 1

    # resume: the user raises the budget — the reply is parsed into an
    # update proposal and the evidence gate confirms it against the verbatim
    asyncio.run(processor.handle_resume(_resume_command(run_id, "预算 4000")))

    assert processor.repository.runs[run_id]["status"] == "COMPLETED"
    final = processor.repository.checkpoints[run_id]
    budget_slot = final.slots.get("budget")
    assert budget_slot.value == "4000"
    assert budget_slot.state == SlotState.USER_OVERRIDE  # user evidence, not agent inference
    builds = [obs for obs in final.observations if obs.tool == "build_itinerary"]
    assert len(builds) >= 2 and builds[-1].ok, "the plan was rebuilt after the adjustment"
    # Test E: the old failure did not poison the resumed planning — exactly
    # one ask happened and the post-resume decision was update, not re-ask
    assert len(_asks(processor)) == 1
    # success resets the failure memory
    assert final.failure_kind is None
    completed = [e for e in processor.published if isinstance(e, AgentCompletedEvent)]
    # AUDIT-01（归边 A）：completed 事件只带摘要 + 槽位，不再携带 itinerary。
    assert completed and completed[0].payload.summary


# ── Test C / D: unusable or unrelated replies never mutate constraints ───────


def test_vague_reply_re_asks_without_mutating_constraints() -> None:
    processor = _RecordingProcessor(builder=_BudgetInfeasibleBuilder())
    asyncio.run(processor.handle_start(_start_command("想去成都玩 10月1日到10月3日，预算 2500")))
    run_id = next(iter(processor.repository.runs))

    asyncio.run(processor.handle_resume(_resume_command(run_id, "随便吧")))

    assert processor.repository.runs[run_id]["status"] == "WAITING_USER"
    final = processor.repository.checkpoints[run_id]
    assert final.slots.get("budget").value == "2500"
    assert final.candidate_itinerary is None
    assert len(_asks(processor)) == 2  # the question repeats, constraints intact


def test_unrelated_reply_keeps_waiting_without_mutating_constraints() -> None:
    processor = _RecordingProcessor(builder=_BudgetInfeasibleBuilder())
    asyncio.run(processor.handle_start(_start_command("想去成都玩 10月1日到10月3日，预算 2500")))
    run_id = next(iter(processor.repository.runs))

    asyncio.run(processor.handle_resume(_resume_command(run_id, "明天天气怎么样？")))

    assert processor.repository.runs[run_id]["status"] == "WAITING_USER"
    final = processor.repository.checkpoints[run_id]
    assert final.slots.get("budget").value == "2500"
    assert final.failure_kind == "USER_CONSTRAINT"
    updates = [
        obs
        for obs in final.observations
        if obs.tool == "update_constraints" and "4000" in obs.summary
    ]
    assert not updates, "an unrelated reply must not produce a constraint update"


# ── Test A / E: must-visit removal closes the loop at the loop level ─────────


def _removal_loop_states() -> tuple[AgentLoop, AgentState, list]:
    slots = (
        ConstraintSlots.empty()
        .fill("destination", "成都", state=SlotState.CONFIRMED)
        .fill("start_date", "2026-10-01", state=SlotState.CONFIRMED)
        .fill("end_date", "2026-10-03", state=SlotState.CONFIRMED)
        .fill("must_visit", ["武侯祠"], state=SlotState.CONFIRMED)
    )
    states: list[AgentState] = []

    async def sink(state: AgentState) -> None:
        states.append(state)

    loop = AgentLoop(
        decider=AskingDecider(),
        tools=ToolRegistry.with_runtime(
            ToolRuntime(
                itinerary_builder=_MustVisitInfeasibleBuilder(),
                feasibility=_gate_factory(),
            )
        ),
    )
    return loop, AgentState(slots=slots), states, sink


def _gate_factory():
    async def gate(**_kwargs: Any) -> Any:
        return SimpleNamespace(has_blocker=False)

    return gate


def test_must_visit_removal_resume_replans_and_emits() -> None:
    import dataclasses

    loop, initial, states, sink = _removal_loop_states()
    first = asyncio.run(run_agent(loop, initial, checkpoint_sink=sink))
    assert first.stop_reason == "WAITING_USER"
    assert states[-1].failure_kind == "USER_CONSTRAINT"
    assert states[-1].failure_attempts == 1
    baseline_observations = len(states[-1].observations)
    checkpoint_before_resume = states[-1]

    # resume with the user's adjustment (mirrors handle_resume's restore)
    resumed = dataclasses.replace(
        states[-1],
        user_message="删除这个必去点",
        stop_reason=None,
        steps=0,
        pending_question=None,
        turn_baseline_observations=baseline_observations,
    )
    second = asyncio.run(run_agent(loop, resumed, checkpoint_sink=sink))

    assert second.stop_reason == "EMITTED", second.stop_reason
    # Test E: the first post-resume decision was the constraint update, and
    # the old failure did not re-trigger the question
    new_observations = second.observations[baseline_observations:]
    assert new_observations[0].tool == "update_constraints"
    assert not any(obs.tool == "ask_user" for obs in new_observations)
    # the removal is recorded on the slot (user evidence, not agent choice)
    final_slot = checkpoint_before_resume.slots.get("must_visit")
    assert states[-1].slots.get("must_visit").state == SlotState.REJECTED
    assert final_slot.value == ["武侯祠"]
    # the success reset the failure memory
    assert states[-1].failure_kind is None


def test_adjustment_parser_unit() -> None:
    decider = AskingDecider()

    def _state(must_visit: list[str] | None, message: str) -> AgentState:
        slots = (
            ConstraintSlots.empty()
            .fill("destination", "成都", state=SlotState.CONFIRMED)
            .fill("start_date", "2026-10-01", state=SlotState.CONFIRMED)
            .fill("end_date", "2026-10-03", state=SlotState.CONFIRMED)
        )
        if must_visit is not None:
            slots = slots.fill("must_visit", list(must_visit), state=SlotState.CONFIRMED)
        return AgentState(slots=slots, user_message=message)

    # named removal keeps the remaining entries
    adjustment = decider._extract_adjustment(
        _state(["武侯祠", "宽窄巷子"], "不要武侯祠了，宽窄巷子还是可以去")
    )
    assert adjustment is not None
    assert adjustment["rejections"] == {"must_visit": "武侯祠"}
    assert adjustment["values"] == {"must_visit": ["宽窄巷子"]}

    # anaphoric removal resolves only with exactly one entry
    single = decider._extract_adjustment(_state(["武侯祠"], "删除这个必去点"))
    assert single is not None
    assert single["rejections"] == {"must_visit": "武侯祠"}

    # ambiguous multi-entry anaphora → re-ask, never guess
    assert (
        decider._extract_adjustment(_state(["武侯祠", "宽窄巷子"], "删除这个必去点"))
        is None
    )

    # unrelated reply → None
    assert decider._extract_adjustment(_state(["武侯祠"], "明天天气怎么样？")) is None

    # budget override parses the raised amount
    budget_adjustment = decider._extract_adjustment(
        _state(None, "预算可以提高到 4000")
    )
    assert budget_adjustment is not None
    assert budget_adjustment["values"] == {"budget": "4000"}


def test_goal_and_memory_survive_the_resume_chain() -> None:
    """Checkpoint consistency (user §十九): after the full
    ask → resume → update → replan → EMITTED chain the persisted state keeps
    a coherent goal/slots/failure-memory snapshot."""
    processor = _RecordingProcessor(builder=_BudgetInfeasibleBuilder())
    asyncio.run(processor.handle_start(_start_command("想去成都玩 10月1日到10月3日，预算 2500")))
    run_id = next(iter(processor.repository.runs))
    before = processor.repository.checkpoints[run_id]
    # the goal is written by the build tool when the BuiltItinerary backend
    # produces one; the plain test builder keeps it empty (documented
    # boundary) — the chain must keep it STABLE either way

    asyncio.run(processor.handle_resume(_resume_command(run_id, "预算 4000")))
    after = processor.repository.checkpoints[run_id]

    # goal stays as written by the builder kind: the plain test builder
    # (non-BuiltItinerary) never derives one — documented boundary
    assert after.goal == before.goal
    assert after.slots.get("destination").value == before.slots.get("destination").value
    assert after.failure_attempts == 0  # success reset the memory
    assert after.decision_summaries == ()
