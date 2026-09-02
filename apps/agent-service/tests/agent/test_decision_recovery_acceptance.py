"""V3 Phase D-Final — canonical acceptance suite for decision & recovery.

One processor-level trajectory per scenario of the Phase D verdict, run over
the REAL chain (AgentDialogProcessor → AskingDecider → classify_failure →
D-2 retry / D-3 repair / D-4 duplicate guard → build_itinerary), plus two
cross-scenario invariants:

- G (constraint safety): no recovery mechanism may change a confirmed user
  constraint without the user's own words as evidence;
- H (safety boundary): none of the scenarios may terminate with
  CEILING_REACHED — every exit is a policy decision (COMPLETED /
  WAITING_USER / STOPPED), the step ceiling is never the reason a run ends.

Pure acceptance cut: zero production code.  Any scenario failing at HEAD is
STOP CONDITION 1 (re-adjudicate), never a test to be patched into silence.
"""

from __future__ import annotations

import asyncio
from typing import Any

from test_duplicate_failure_guard import _CapacityBuilder
from test_infeasible_resume import _BudgetInfeasibleBuilder
from test_transient_retry import (
    _START_MESSAGE,
    _asks,
    _counting,
    _RecordingProcessor,
    _resume_command,
    _ScriptedBuilder,
    _start_command,
)

from trip_agent.agent.state import SlotState
from trip_agent.worker.contracts import (
    AgentCompletedEvent,
    AgentRunFinishedEvent,
    AgentStepEvent,
)

# the user's constraints as the start message confirms them — scenario G
# compares every checkpoint against this exact shape
_EXPECTED_SLOTS: dict[str, str] = {
    "destination": "成都",
    "start_date": "10月1日",
    "end_date": "10月3日",
    "budget": "2500",
}


def _start(processor: Any, message: str = _START_MESSAGE) -> str:
    asyncio.run(processor.handle_start(_start_command(message)))
    return next(iter(processor.repository.runs))


def _resume(processor: Any, run_id: str, answer: str) -> None:
    asyncio.run(processor.handle_resume(_resume_command(run_id, answer)))


def _status(processor: Any, run_id: str) -> str:
    return processor.repository.runs[run_id]["status"]


def _checkpoint(processor: Any, run_id: str) -> Any:
    return processor.repository.checkpoints[run_id]


def _builds(checkpoint: Any) -> list[Any]:
    return [obs for obs in checkpoint.observations if obs.tool == "build_itinerary"]


def _assert_no_ceiling(processor: Any, run_id: str, *, scenario: str) -> None:
    """Invariant H for one turn: the finish payload may never blame the
    step ceiling."""
    finished = [e for e in processor.published if isinstance(e, AgentRunFinishedEvent)]
    for event in finished:
        reason = event.payload.reason_code
        assert reason != "CEILING_REACHED", (
            f"scenario {scenario} terminated on the safety ceiling, not a policy decision"
        )


def _assert_slots_untouched(checkpoint: Any, *, scenario: str) -> None:
    """Invariant G: every confirmed constraint still holds the user's own
    value."""
    for name, expected in _EXPECTED_SLOTS.items():
        slot = checkpoint.slots.get(name)
        assert slot.value == expected, (
            f"scenario {scenario}: slot '{name}' changed to {slot.value!r} "
            f"without user evidence (expected {expected!r})"
        )
        assert slot.state in (SlotState.CONFIRMED, SlotState.USER_OVERRIDE)


def _memory(checkpoint: Any) -> tuple[str | None, str | None, int]:
    return checkpoint.failure_kind, checkpoint.failure_signature, checkpoint.failure_attempts


def _only_run_id(processor: Any) -> str:
    assert len(processor.repository.runs) == 1
    return next(iter(processor.repository.runs))


# ── Scenario A: TRANSIENT failure → bounded retry → success ─────────────────


def test_scenario_a_transient_failure_retries_once_then_completes() -> None:
    builder, calls = _counting(_ScriptedBuilder("PROVIDER_TIMEOUT"))
    processor = _RecordingProcessor(builder=builder)
    run_id = _start(processor)

    assert _status(processor, run_id) == "COMPLETED"
    assert len(calls) == 2, "exactly one agent-level retry, no more"

    checkpoint = _checkpoint(processor, run_id)
    builds = _builds(checkpoint)
    assert [obs.ok for obs in builds] == [False, True]
    assert builds[0].error_code == "PROVIDER_TIMEOUT"
    # success cleared the failure memory completely (D-1 reset semantics)
    assert _memory(checkpoint) == (None, None, 0)
    assert checkpoint.candidate_itinerary is not None

    completed = [e for e in processor.published if isinstance(e, AgentCompletedEvent)]
    # AUDIT-01（归边 A）：completed 事件不再携带 itinerary，仅摘要 + 槽位。
    assert len(completed) == 1 and completed[0].payload.summary
    # the retry was a declared decision, not a silent re-run
    steps = [e for e in processor.published if isinstance(e, AgentStepEvent)]
    assert [s.payload.tool for s in steps] == [
        "update_constraints",
        "build_itinerary",
        "build_itinerary",
        "validate_itinerary",
    ]
    _assert_slots_untouched(checkpoint, scenario="A")
    _assert_no_ceiling(processor, run_id, scenario="A")


# ── Scenario B: TRANSIENT exhausted → WAITING_USER, memory preserved ────────


def test_scenario_b_exhausted_transient_exits_to_the_user_with_memory() -> None:
    processor = _RecordingProcessor(builder=_ScriptedBuilder("PROVIDER_TIMEOUT", repeat_last=True))
    run_id = _start(processor)

    assert _status(processor, run_id) == "WAITING_USER"
    checkpoint = _checkpoint(processor, run_id)
    # D-2: the initial attempt plus ONE bounded retry — never more
    assert len(_builds(checkpoint)) == 2
    assert _memory(checkpoint) == (
        "TRANSIENT",
        "TRANSIENT:build_itinerary:PROVIDER_TIMEOUT",
        2,
    )
    assert checkpoint.candidate_itinerary is None
    asks = _asks(processor)
    assert len(asks) == 1, "the outage is surfaced exactly once"
    assert asks[0].payload.question
    _assert_slots_untouched(checkpoint, scenario="B")
    _assert_no_ceiling(processor, run_id, scenario="B")


# ── Scenario C: USER_CONSTRAINT failure → ask → user change → replan ────────


def test_scenario_c_user_constraint_adjustment_replans_and_completes() -> None:
    processor = _RecordingProcessor(builder=_BudgetInfeasibleBuilder())
    run_id = _start(processor)

    assert _status(processor, run_id) == "WAITING_USER"
    checkpoint = _checkpoint(processor, run_id)
    assert _memory(checkpoint)[0] == "USER_CONSTRAINT"
    assert len(_asks(processor)) == 1

    # only the USER's own words move the constraint
    _assert_slots_untouched(checkpoint, scenario="C (before resume)")

    _resume(processor, run_id, "预算 4000")

    assert _status(processor, run_id) == "COMPLETED"
    final = _checkpoint(processor, run_id)
    budget = final.slots.get("budget")
    assert budget.value == "4000"
    assert budget.state == SlotState.USER_OVERRIDE  # evidence was the user's reply
    assert budget.evidence and "4000" in str(budget.evidence)
    # the other constraints never moved
    for name in ("destination", "start_date", "end_date"):
        assert final.slots.get(name).value == _EXPECTED_SLOTS[name]
    builds = _builds(final)
    assert len(builds) >= 2 and builds[-1].ok
    assert _memory(final) == (None, None, 0), "success resets the failure memory"
    assert len(_asks(processor)) == 1, "no re-ask after a valid adjustment"
    _assert_no_ceiling(processor, run_id, scenario="C")


# ── Scenario D: invalid resume → failure memory preserved, nothing guessed ──


def test_scenario_d_vague_resume_preserves_user_constraint_memory() -> None:
    processor = _RecordingProcessor(builder=_BudgetInfeasibleBuilder())
    run_id = _start(processor)
    before = _memory(_checkpoint(processor, run_id))
    assert before[0] == "USER_CONSTRAINT"
    updates_before = len(
        [
            obs
            for obs in _checkpoint(processor, run_id).observations
            if obs.tool == "update_constraints"
        ]
    )

    _resume(processor, run_id, "随便吧")

    assert _status(processor, run_id) == "WAITING_USER"
    checkpoint = _checkpoint(processor, run_id)
    assert _memory(checkpoint) == before, "memory survives an unusable reply"
    assert checkpoint.candidate_itinerary is None
    updates_after = len(
        [obs for obs in checkpoint.observations if obs.tool == "update_constraints"]
    )
    assert updates_after == updates_before, "an unusable reply must not become a guessed adjustment"
    assert len(_asks(processor)) == 2, "the question repeats — the loop does not"
    _assert_slots_untouched(checkpoint, scenario="D (USER_CONSTRAINT)")
    _assert_no_ceiling(processor, run_id, scenario="D")


def test_scenario_d_vague_resume_preserves_feasibility_memory() -> None:
    processor = _RecordingProcessor(builder=_CapacityBuilder())
    run_id = _start(processor)
    before = _memory(_checkpoint(processor, run_id))
    assert before[0] == "FEASIBILITY"

    _resume(processor, run_id, "随便吧")

    assert _status(processor, run_id) == "WAITING_USER"
    checkpoint = _checkpoint(processor, run_id)
    assert _memory(checkpoint) == before
    assert len(_builds(checkpoint)) == 1, "no rebuild was attempted for a vague reply"
    _assert_slots_untouched(checkpoint, scenario="D (FEASIBILITY)")
    _assert_no_ceiling(processor, run_id, scenario="D")


# ── Scenario E: duplicate failure — escalation, then bounded user consent ───


def test_scenario_e_duplicate_failure_escalates_and_consent_stays_bounded() -> None:
    processor = _RecordingProcessor(builder=_ScriptedBuilder("PROVIDER_TIMEOUT", repeat_last=True))
    run_id = _start(processor)

    # D-2 bound reached on the first turn
    assert _status(processor, run_id) == "WAITING_USER"
    assert len(_builds(_checkpoint(processor, run_id))) == 2

    # user consent is a recovery action — one bounded rebuild…
    _resume(processor, run_id, "再试一次")
    assert _status(processor, run_id) == "WAITING_USER"
    assert len(_builds(_checkpoint(processor, run_id))) == 3

    # …but consent cannot re-earn an unbounded retry: once the budget
    # (3) + 1 builds have failed, the next repetition is vetoed by the guard
    _resume(processor, run_id, "再试一次")
    assert _status(processor, run_id) == "STOPPED"
    final = _checkpoint(processor, run_id)
    assert len(_builds(final)) == 4, "budget 3 + one consent rebuild, then STOPPED"
    # the failure memory describes what actually happened, unreset by exits
    assert _memory(final) == (
        "TRANSIENT",
        "TRANSIENT:build_itinerary:PROVIDER_TIMEOUT",
        4,
    )
    _assert_slots_untouched(final, scenario="E")
    _assert_no_ceiling(processor, run_id, scenario="E")


# ── Scenario F: a DIFFERENT failure is not mistaken for a repeated one ──────


def test_scenario_f_a_changed_failure_gets_a_fresh_attempt() -> None:
    processor = _RecordingProcessor(
        builder=_ScriptedBuilder("PROVIDER_TIMEOUT", "RATE_LIMITED", repeat_last=True)
    )
    run_id = _start(processor)

    # build 1 fails PROVIDER_TIMEOUT; the retry hits a DIFFERENT transient
    # error — the signature changes, attempts drop back to 1, and the new
    # failure re-earns exactly one bounded retry instead of inheriting the
    # old counter (a changed failure is never a "duplicate")
    assert _status(processor, run_id) == "WAITING_USER"
    checkpoint = _checkpoint(processor, run_id)
    builds = _builds(checkpoint)
    assert [obs.ok for obs in builds] == [False, False, False]
    assert [obs.error_code for obs in builds] == [
        "PROVIDER_TIMEOUT",
        "RATE_LIMITED",
        "RATE_LIMITED",
    ]
    assert _memory(checkpoint) == (
        "TRANSIENT",
        "TRANSIENT:build_itinerary:RATE_LIMITED",
        2,
    )
    assert len(_asks(processor)) == 1, "the exit is the outage notice, not the ceiling"
    _assert_slots_untouched(checkpoint, scenario="F")
    _assert_no_ceiling(processor, run_id, scenario="F")


# ── Invariant G across every scenario: constraints move only with evidence ──


def test_invariant_g_no_recovery_mechanism_edits_constraints_on_its_own() -> None:
    runs: list[tuple[str, Any]] = []
    for name, builder, resumes in (
        ("A", _ScriptedBuilder("PROVIDER_TIMEOUT"), ()),
        ("B", _ScriptedBuilder("PROVIDER_TIMEOUT", repeat_last=True), ()),
        ("C", _BudgetInfeasibleBuilder(), ("预算 4000",)),
        ("D", _BudgetInfeasibleBuilder(), ("随便吧",)),
        ("D/FEASIBILITY", _CapacityBuilder(), ("随便吧",)),
        ("E", _ScriptedBuilder("PROVIDER_TIMEOUT", repeat_last=True), ("再试一次", "再试一次")),
        ("F", _ScriptedBuilder("PROVIDER_TIMEOUT", "RATE_LIMITED", repeat_last=True), ()),
    ):
        processor = _RecordingProcessor(builder=builder)
        run_id = _start(processor)
        for answer in resumes:
            _resume(processor, run_id, answer)
        runs.append((name, processor.repository.checkpoints[run_id]))

    for name, checkpoint in runs:
        for slot_name, expected in _EXPECTED_SLOTS.items():
            if name == "C" and slot_name == "budget":
                continue  # the ONE user-owned change, asserted in scenario C
            slot = checkpoint.slots.get(slot_name)
            assert slot.value == expected, f"scenario {name} moved '{slot_name}' to {slot.value!r}"


def test_invariant_h_no_scenario_ever_ends_on_the_step_ceiling() -> None:
    """Every terminal status in this suite is a policy decision.  The one
    status that would prove the loops only stop via CEILING does not exist."""
    for name, builder, resumes in (
        ("A", _ScriptedBuilder("PROVIDER_TIMEOUT"), ()),
        ("B", _ScriptedBuilder("PROVIDER_TIMEOUT", repeat_last=True), ()),
        ("C", _BudgetInfeasibleBuilder(), ("预算 4000",)),
        ("D", _BudgetInfeasibleBuilder(), ("随便吧",)),
        ("D/FEASIBILITY", _CapacityBuilder(), ("随便吧",)),
        ("E", _ScriptedBuilder("PROVIDER_TIMEOUT", repeat_last=True), ("再试一次", "再试一次")),
        ("F", _ScriptedBuilder("PROVIDER_TIMEOUT", "RATE_LIMITED", repeat_last=True), ()),
    ):
        processor = _RecordingProcessor(builder=builder)
        run_id = _start(processor)
        for answer in resumes:
            _resume(processor, run_id, answer)
        status = processor.repository.runs[run_id]["status"]
        assert status in {"COMPLETED", "WAITING_USER", "STOPPED"}, (
            f"scenario {name} ended in unexpected status {status!r}"
        )
        _assert_no_ceiling(processor, run_id, scenario=name)
