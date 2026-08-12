from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from plan_evaluation_support import make_activity, make_command, make_result, make_transit

from trip_agent.feasibility.inputs import (
    ActivityLocator,
    ValidationInputs,
    VisitDurationBinding,
)
from trip_agent.feasibility.repair.engine import apply_repair_plan, plan_repairs
from trip_agent.feasibility.repair.session import (
    RepairSession,
    RepairStopReason,
    advance_repair_session,
    start_repair_session,
)
from trip_agent.feasibility.validator import run_validation
from trip_agent.planning.visit_duration import (
    DurationProfileSource,
    VisitDurationProfile,
)

_REPORT_ID = UUID("4d9b7e0a-3c2f-4a1b-9e8d-7f6e5d4c3b2a")
_VALIDATED_AT = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


def _run(
    *,
    activity_index: int = 0,
    duration_minutes: int = 20,
    eligible: bool = True,
):
    activity = make_activity(
        activity_index,
        source="AMAP",
        kind="ATTRACTION",
        duration_minutes=duration_minutes,
    )
    result = make_result(
        activities=(activity,),
        transit_legs=(),
        estimated_total_cost=Decimal("100.00"),
        provider="AMAP",
    )
    inputs = ValidationInputs(
        visit_duration_bindings=(
            VisitDurationBinding(
                activity=ActivityLocator(0, 0),
                profile=VisitDurationProfile(
                    min_minutes=45,
                    recommended_minutes=90,
                    max_minutes=120,
                    source=DurationProfileSource.OFFICIAL_FACT,
                    source_ref=f"official:{activity_index}",
                    confidence=0.9,
                    profile_version="official-v1",
                    hard_constraint_eligible=eligible,
                ),
            ),
        )
    )
    return run_validation(
        command=make_command(),
        itinerary=result.itinerary,
        report_id=_REPORT_ID,
        validated_at=_VALIDATED_AT,
        validation_inputs=inputs,
    )


def _advance(session: RepairSession, after_run) -> RepairSession:
    plan = plan_repairs(session.current, attempt_index=len(session.attempts) + 1)
    assert plan is not None
    return advance_repair_session(session, plan=plan, after=after_run)


def test_unchanged_fingerprint_stops_after_one_recorded_attempt() -> None:
    initial = _run()
    session = start_repair_session(initial)

    stopped = _advance(session, initial)

    assert stopped.stop_reason is RepairStopReason.NO_PROGRESS
    assert len(stopped.attempts) == 1
    attempt = stopped.attempts[0]
    assert attempt.before_fingerprint == attempt.after_fingerprint
    assert attempt.action_codes == ("CLAMP_VISIT_DURATION",)
    assert stopped.current.report.repair_attempts == stopped.attempts


def test_repeated_failure_signature_stops_even_when_fingerprint_changes() -> None:
    initial = _run(activity_index=0, duration_minutes=20)
    session = start_repair_session(initial)
    after_one = _run(activity_index=1, duration_minutes=20)
    session = _advance(session, after_one)
    assert session.stop_reason is None

    repeated = _run(activity_index=0, duration_minutes=20)
    stopped = _advance(session, repeated)

    assert stopped.stop_reason is RepairStopReason.REPEATED_FAILURE
    assert len(stopped.attempts) == 2


def test_unknown_result_stops_without_guessing_evidence() -> None:
    initial = _run(eligible=True)
    session = start_repair_session(initial)
    unverified = _run(activity_index=1, eligible=False)

    stopped = _advance(session, unverified)

    assert stopped.stop_reason is RepairStopReason.UNVERIFIED
    assert len(stopped.attempts) == 1


def test_three_attempt_limit_is_hard_and_history_is_contiguous() -> None:
    session = start_repair_session(_run(activity_index=0))
    for activity_index in (1, 2, 3):
        session = _advance(session, _run(activity_index=activity_index))

    assert session.stop_reason is RepairStopReason.ATTEMPT_LIMIT
    assert tuple(attempt.attempt_index for attempt in session.attempts) == (1, 2, 3)
    assert session.current.report.repair_attempts == session.attempts
    assert plan_repairs(session.current, attempt_index=4) is None


def test_start_session_stops_when_no_supported_action_exists() -> None:
    unsupported = run_validation(
        command=make_command(budget_amount=Decimal("100.00")),
        itinerary=make_result(estimated_total_cost=Decimal("200.00")).itinerary,
        report_id=_REPORT_ID,
        validated_at=_VALIDATED_AT,
    )

    session = start_repair_session(unsupported)

    assert session.stop_reason is RepairStopReason.NO_LEGAL_ACTION
    assert session.attempts == ()


def test_seventeen_duration_failures_continue_into_a_second_attempt() -> None:
    base = datetime(2026, 8, 1, tzinfo=UTC)
    activities = tuple(
        make_activity(
            index,
            start_hour=0,
            kind="ATTRACTION",
            duration_minutes=20,
        ).model_copy(
            update={
                "start_time": base + timedelta(minutes=index * 60),
                "end_time": base + timedelta(minutes=index * 60 + 20),
            }
        )
        for index in range(17)
    )
    result = make_result(
        activities=activities,
        transit_legs=tuple(make_transit(index) for index in range(16)),
    )
    inputs = ValidationInputs(
        visit_duration_bindings=tuple(
            VisitDurationBinding(
                activity=ActivityLocator(0, index),
                profile=VisitDurationProfile(
                    min_minutes=45,
                    recommended_minutes=60,
                    max_minutes=120,
                    source=DurationProfileSource.OFFICIAL_FACT,
                    source_ref=f"official:{index}",
                    confidence=0.9,
                    profile_version="official-v1",
                    hard_constraint_eligible=True,
                ),
            )
            for index in range(17)
        )
    )
    initial = run_validation(
        command=make_command(),
        itinerary=result.itinerary,
        report_id=_REPORT_ID,
        validated_at=_VALIDATED_AT,
        validation_inputs=inputs,
    )
    session = start_repair_session(initial)
    first_plan = plan_repairs(initial, attempt_index=1)
    assert first_plan is not None
    assert len(first_plan.actions) == 16
    first_applied = apply_repair_plan(initial, first_plan)
    after_first = run_validation(
        command=initial.context.command,
        itinerary=first_applied.candidate.itinerary,
        report_id=_REPORT_ID,
        validated_at=_VALIDATED_AT,
        validation_inputs=first_applied.candidate.validation_inputs,
    )

    session = advance_repair_session(session, plan=first_plan, after=after_first)

    assert session.stop_reason is None
    second_plan = plan_repairs(session.current, attempt_index=2)
    assert second_plan is not None
    assert len(second_plan.actions) == 1
