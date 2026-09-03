"""V3 D-4 — the duplicate failure guard: CEILING stops being a policy exit.

Before D-4 every deterministic refusal (infeasible plan, opaque tool error,
empty candidate set, blocked structural gate) drove the loop into repeating the
SAME action under the SAME state until it hit ``MAX_STEPS`` — so
``CEILING_REACHED`` was the ONLY exit for those scenarios (Phase D-4 verdict,
Fact B: L1/L1b/L2/L4 all stopped at steps=8).

The guard reads what D-1/D-3 already remember (``failure_kind`` +
``failure_signature`` + ``failure_attempts``), recognises "the action I am
about to send is the action that just failed, and nothing has changed since",
and escalates instead: a question when only the user can change the outcome,
the loop's existing ``"STOPPED"`` exit when they cannot.  It never writes
state, never vetoes ``ask_user``/``update_constraints``, and clears nothing —
D-3's constraint reset stays the single release path (so Tests C/D prove the
guard is both effective AND survivable).

Tests run the REAL chain (ToolObservation → classify_failure → AskingDecider →
ToolRegistry) exactly as D-1/D-2/D-3 do.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from test_transient_retry import (
    _START_MESSAGE,
    _asks,
    _collector,
    _confirmed_slots,
    _counting,
    _gate,
    _itinerary,
    _RecordingProcessor,
    _resume_command,
    _ScriptedBuilder,
    _start_command,
)

from trip_agent.agent.failure_policy import (
    FAILURE_REPEAT_BUDGET,
    MAX_TRANSIENT_SAME_FAILURE_ACTIONS,
    USER_OWNED_KINDS,
    escalate_duplicate,
    signature_tool,
)
from trip_agent.agent.graph import MAX_STEPS, AgentLoop, AskingDecider, run_agent
from trip_agent.agent.state import AgentState, ConstraintSlots, SlotState
from trip_agent.agent.tools import ToolRegistry, ToolRuntime
from trip_agent.domain.planning.protocols import (
    OptimizationConflict,
    PlanningInfeasibleError,
)

_CAPACITY_CONFLICT = "3 天的可游玩容量不足以容纳全部安排"


class _CapacityBuilder:
    """Deterministic refusal: while the confirmed budget is below 3000 the plan
    is infeasible for a FEASIBILITY reason (same input ⇒ same refusal), and
    raising the budget is the only way out."""

    async def __call__(self, *, slots: Any, trip_id: str | None = None) -> Any:
        budget = slots.confirmed_values().get("budget")
        if budget is not None and Decimal(str(budget)) < Decimal("3000"):
            raise PlanningInfeasibleError(
                conflicts=(
                    OptimizationConflict(
                        "INSUFFICIENT_DAY_CAPACITY",
                        _CAPACITY_CONFLICT,
                        ("capacity",),
                    ),
                ),
                relaxations=(),
            )
        return _itinerary()


def _blocked_gate() -> Any:
    async def gate(**_kwargs: Any) -> Any:
        return SimpleNamespace(has_blocker=True)

    return gate


def _run(
    builder: Any,
    *,
    gate: Any = None,
    slots: ConstraintSlots | None = None,
    message: str = _START_MESSAGE,
) -> tuple[Any, list[AgentState]]:
    """One real loop over the real registry/decider, collecting every snapshot."""
    loop = AgentLoop(
        decider=AskingDecider(),
        tools=ToolRegistry.with_runtime(
            ToolRuntime(itinerary_builder=builder, feasibility=gate or _gate())
        ),
    )
    states, sink = _collector()
    result = asyncio.run(
        run_agent(
            loop,
            AgentState(slots=slots or _confirmed_slots(), user_message=message),
            checkpoint_sink=sink,
        )
    )
    return result, states


def _tools_of(result: Any) -> list[str]:
    return [observation.tool for observation in result.observations]


def _builds(result: Any) -> list[Any]:
    return [obs for obs in result.observations if obs.tool == "build_itinerary"]


def _questions(result: Any) -> list[str]:
    return [obs.summary for obs in result.observations if obs.tool == "ask_user"]


# ── the guard's judgement, as pure functions ─────────────────────────────────


def test_the_failing_tool_is_readable_from_the_signature() -> None:
    assert signature_tool("FEASIBILITY:build_itinerary:INSUFFICIENT_DAY_CAPACITY") == (
        "build_itinerary"
    )
    assert signature_tool("FEASIBILITY:validate_itinerary") == "validate_itinerary"
    assert signature_tool(None) is None
    assert signature_tool("") is None
    assert signature_tool("FEASIBILITY") is None


def test_every_failure_kind_has_exactly_one_repeat_budget() -> None:
    assert set(FAILURE_REPEAT_BUDGET) == {
        "TRANSIENT",
        "CAPABILITY_MISSING",
        "USER_CONSTRAINT",
        "CANDIDATE_EMPTY",
        "FEASIBILITY",
        "VALIDATION",
        "INTERNAL",
    }
    # only the provider-outage kind is allowed several attempts (D-2's retry
    # plus the rebuilds the user authorizes); every deterministic refusal
    # refuses twice for the same reason, so a second attempt is worthless.
    assert FAILURE_REPEAT_BUDGET["TRANSIENT"] == MAX_TRANSIENT_SAME_FAILURE_ACTIONS
    deterministic = {
        kind: budget for kind, budget in FAILURE_REPEAT_BUDGET.items() if kind != "TRANSIENT"
    }
    assert set(deterministic) == set(FAILURE_REPEAT_BUDGET) - {"TRANSIENT"}
    assert set(deterministic.values()) == {0}


def test_only_user_owned_kinds_escalate_to_a_question() -> None:
    assert frozenset(
        {"USER_CONSTRAINT", "CANDIDATE_EMPTY", "FEASIBILITY", "VALIDATION"}
    ) == USER_OWNED_KINDS
    for kind in USER_OWNED_KINDS:
        assert escalate_duplicate(
            kind=kind,
            signature=f"{kind}:build_itinerary:X",
            attempts=1,
            action_tool="build_itinerary",
        ) == "ASK_USER"
    for kind in ("TRANSIENT", "INTERNAL", "CAPABILITY_MISSING"):
        assert escalate_duplicate(
            kind=kind,
            signature=f"{kind}:build_itinerary:X",
            attempts=99,
            action_tool="build_itinerary",
        ) == "STOPPED"


def test_an_unresolved_failure_never_escalates_and_attempts_alone_is_not_enough() -> None:
    assert escalate_duplicate(
        kind=None, signature=None, attempts=0, action_tool="build_itinerary"
    ) is None
    # resolved memory (kind cleared) can never trip the guard
    assert escalate_duplicate(
        kind=None,
        signature="FEASIBILITY:build_itinerary:X",
        attempts=5,
        action_tool="build_itinerary",
    ) is None
    # a different action than the one that failed is always allowed — this is
    # what keeps ask_user and update_constraints outside the guard's reach
    for tool in ("ask_user", "update_constraints", "update_preferences"):
        assert escalate_duplicate(
            kind="FEASIBILITY",
            signature="FEASIBILITY:build_itinerary:X",
            attempts=7,
            action_tool=tool,
        ) is None
    # transient keeps its authorized attempts; the bound is the last one
    for attempts in range(1, MAX_TRANSIENT_SAME_FAILURE_ACTIONS + 1):
        assert escalate_duplicate(
            kind="TRANSIENT",
            signature="TRANSIENT:build_itinerary:PROVIDER_TIMEOUT",
            attempts=attempts,
            action_tool="build_itinerary",
        ) is None
    assert escalate_duplicate(
        kind="TRANSIENT",
        signature="TRANSIENT:build_itinerary:PROVIDER_TIMEOUT",
        attempts=MAX_TRANSIENT_SAME_FAILURE_ACTIONS + 1,
        action_tool="build_itinerary",
    ) == "STOPPED"


# ── Test A: the same failure no longer builds forever ────────────────────────


def test_a_deterministic_refusal_asks_after_one_build() -> None:
    builder, calls = _counting(_CapacityBuilder())
    result, states = _run(builder)

    assert result.stop_reason == "WAITING_USER", result.stop_reason
    assert len(calls) == 1, "the refused build is never issued a second time"
    assert _tools_of(result) == ["build_itinerary", "ask_user"]
    assert result.steps < MAX_STEPS

    # the guard reads the memory but writes nothing to it
    final = states[-1]
    assert final.failure_kind == "FEASIBILITY"
    assert final.failure_signature == (
        f"FEASIBILITY:build_itinerary:{'INSUFFICIENT_DAY_CAPACITY'}"
    )
    assert final.failure_attempts == 1

    # the question says WHICH conflict and WHAT only the user can change
    question = _questions(result)[-1]
    assert _CAPACITY_CONFLICT in question
    assert "放宽日期" in question and "必去地点" in question and "预算" in question


# ── Test G: CEILING is no longer the exit for deterministic repeats ──────────


@pytest.mark.parametrize(
    ("label", "builder", "gate", "expected_stop", "max_actions"),
    [
        ("infeasible plan", _CapacityBuilder(), None, "WAITING_USER", 1),
        (
            "empty candidate set",
            _ScriptedBuilder("NO_RESULT", repeat_last=True),
            None,
            "WAITING_USER",
            1,
        ),
        (
            "opaque internal error",
            _ScriptedBuilder(RuntimeError("boom"), repeat_last=True),
            None,
            "STOPPED",
            1,
        ),
    ],
)
def test_ceiling_is_not_the_exit_for_a_deterministic_repeat(
    label: str,
    builder: Any,
    gate: Any,
    expected_stop: str,
    max_actions: int,
) -> None:
    counted, calls = _counting(builder)
    result, _states = _run(counted, gate=gate)

    assert result.stop_reason == expected_stop, label
    assert result.stop_reason != "CEILING_REACHED"
    assert len(calls) <= max_actions, label
    assert result.steps <= 3, f"{label} escalated in {result.steps} steps"


def test_a_permanently_blocked_structural_gate_asks_instead_of_gating_forever() -> None:
    result, states = _run(_ScriptedBuilder(), gate=_blocked_gate())

    assert result.stop_reason == "WAITING_USER"
    assert _tools_of(result) == [
        "build_itinerary",
        "validate_itinerary",
        "ask_user",
    ], "the gate ran once, not seven times"
    final = states[-1]
    assert final.failure_kind == "FEASIBILITY"
    assert final.failure_attempts == 1
    assert "feasibility gate: blocked" in _questions(result)[-1]


# ── Test B: a different failure is never mistaken for a repeat ───────────────


def test_a_different_failure_resets_the_repeat_judgement() -> None:
    """Transient first, then a deterministic refusal: the second failure is a
    NEW signature, so it must be judged on its own (attempts back to 1) —
    never as the tail of the transient streak, and never as a stop."""
    builder, calls = _counting(
        _ScriptedBuilder(
            "PROVIDER_TIMEOUT",
            PlanningInfeasibleError(
                conflicts=(
                    OptimizationConflict(
                        "INSUFFICIENT_DAY_CAPACITY", _CAPACITY_CONFLICT, ("capacity",)
                    ),
                ),
                relaxations=(),
            ),
            repeat_last=True,
        )
    )
    result, states = _run(builder)

    assert len(calls) == 2, "the authorized transient retry, then the refusal"
    final = states[-1]
    assert final.failure_kind == "FEASIBILITY"
    assert final.failure_attempts == 1, "a new signature restarts the count at 1"
    assert result.stop_reason == "WAITING_USER", "escalated as FEASIBILITY, not stopped"
    assert _questions(result)[-1].startswith("这几次规划都卡在同一个冲突上")


# ── Test C: one real user change releases the guard ──────────────────────────


def test_a_real_constraint_change_releases_the_guard_and_replans() -> None:
    processor = _RecordingProcessor(builder=_CapacityBuilder())
    asyncio.run(processor.handle_start(_start_command(_START_MESSAGE)))
    run_id = next(iter(processor.repository.runs))
    assert processor.repository.runs[run_id]["status"] == "WAITING_USER"
    first_turn = processor.repository.checkpoints[run_id]
    assert [obs.tool for obs in first_turn.observations] == [
        "update_constraints",  # the start message parsed into the confirmed slots
        "build_itinerary",
        "ask_user",
    ]

    asyncio.run(processor.handle_resume(_resume_command(run_id, "预算 4000")))

    final = processor.repository.checkpoints[run_id]
    assert processor.repository.runs[run_id]["status"] == "COMPLETED"
    assert final.stop_reason == "EMITTED", final.stop_reason
    assert final.slots.get("budget").value == "4000"
    assert final.failure_kind is None, "the constraint update cleared the memory"
    builds = _builds(final)
    assert [obs.ok for obs in builds] == [False, True]
    assert len(_asks(processor)) == 1, "the guard asked once and the change closed the loop"


# ── Test D: an invalid reply keeps the memory and sends no new build ─────────


def test_an_unresolvable_reply_keeps_the_memory_and_sends_no_new_build() -> None:
    processor = _RecordingProcessor(builder=_CapacityBuilder())
    asyncio.run(processor.handle_start(_start_command(_START_MESSAGE)))
    run_id = next(iter(processor.repository.runs))

    asyncio.run(processor.handle_resume(_resume_command(run_id, "随便吧")))

    assert processor.repository.runs[run_id]["status"] == "WAITING_USER"
    final = processor.repository.checkpoints[run_id]
    assert final.failure_kind == "FEASIBILITY"
    assert final.failure_attempts == 1, "asking does not count as a repeat"
    assert final.slots.get("budget").value == "2500", "a vague reply changes nothing"
    assert len(_builds(final)) == 1, "the refused build was not repeated"
    assert len(_asks(processor)) == 2, "the question repeats, the action does not"


# ── Test E: user authorizations cannot reform an unbounded retry ─────────────


def test_repeated_user_consent_cannot_keep_a_transient_retry_alive() -> None:
    processor = _RecordingProcessor(
        builder=_ScriptedBuilder("PROVIDER_TIMEOUT", repeat_last=True)
    )
    asyncio.run(processor.handle_start(_start_command(_START_MESSAGE)))
    run_id = next(iter(processor.repository.runs))
    # D-2 turn: first attempt + one automatic retry, then the outage notice
    assert len(_builds(processor.repository.checkpoints[run_id])) == 2
    assert processor.repository.checkpoints[run_id].failure_attempts == 2

    asyncio.run(processor.handle_resume(_resume_command(run_id, "再试一次")))
    first_consent = processor.repository.checkpoints[run_id]
    assert len(_builds(first_consent)) == 3
    assert first_consent.failure_attempts == MAX_TRANSIENT_SAME_FAILURE_ACTIONS
    assert processor.repository.runs[run_id]["status"] == "WAITING_USER"

    asyncio.run(processor.handle_resume(_resume_command(run_id, "再试一次")))
    final = processor.repository.checkpoints[run_id]
    assert processor.repository.runs[run_id]["status"] == "STOPPED"
    assert final.stop_reason == "STOPPED"
    assert len(_builds(final)) == MAX_TRANSIENT_SAME_FAILURE_ACTIONS + 1
    assert len(_asks(processor)) == 2, "the third cycle stopped instead of asking again"


# ── Test F: the ordinary clarification loop is untouched ─────────────────────


def test_the_normal_clarification_loop_never_meets_the_guard() -> None:
    slots = ConstraintSlots.empty().fill(
        "destination", "成都", state=SlotState.CONFIRMED, evidence="成都"
    )
    result, states = _run(
        _ScriptedBuilder(), slots=slots, message="想去成都玩"
    )

    assert result.stop_reason == "WAITING_USER"
    assert [obs.tool for obs in result.observations] == ["ask_user"], (
        "no planning action, therefore nothing for the guard to judge"
    )
    for snapshot in states:
        assert snapshot.failure_kind is None
        assert snapshot.failure_attempts == 0

    processor = _RecordingProcessor(builder=_ScriptedBuilder())
    asyncio.run(processor.handle_start(_start_command("想去成都玩")))
    run_id = next(iter(processor.repository.runs))
    asyncio.run(processor.handle_resume(_resume_command(run_id, _START_MESSAGE)))

    final = processor.repository.checkpoints[run_id]
    assert final.stop_reason == "EMITTED", final.stop_reason
    assert len(_asks(processor)) == 1
    assert final.failure_kind is None
    assert final.slots.get("budget").value == "2500"
