from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from plan_evaluation_support import make_activity, make_command, make_result

from trip_agent.feasibility.inputs import (
    ActivityLocator,
    ValidationInputs,
    VisitDurationBinding,
)
from trip_agent.feasibility.models import (
    FeasibilityStatus,
    RepairAttempt,
    RuleOutcome,
)
from trip_agent.feasibility.validator import run_validation, validate_itinerary
from trip_agent.planning.visit_duration import (
    DurationProfileSource,
    VisitDurationProfile,
)

_REPORT_ID = UUID("4d9b7e0a-3c2f-4a1b-9e8d-7f6e5d4c3b2a")
_VALIDATED_AT = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


def _eligible_profile() -> VisitDurationProfile:
    return VisitDurationProfile(
        min_minutes=45,
        recommended_minutes=90,
        max_minutes=120,
        source=DurationProfileSource.OFFICIAL_FACT,
        source_ref="official:poi-1",
        confidence=0.9,
        profile_version="official-v1",
        hard_constraint_eligible=True,
    )


def _run(*, cost: Decimal = Decimal("100.00")):
    activity = make_activity(
        0,
        source="AMAP",
        kind="ATTRACTION",
        duration_minutes=20,
    )
    result = make_result(
        activities=(activity,),
        transit_legs=(),
        estimated_total_cost=cost,
        provider="AMAP",
    )
    inputs = ValidationInputs(
        visit_duration_bindings=(
            VisitDurationBinding(
                activity=ActivityLocator(day_index=0, activity_index=0),
                profile=_eligible_profile(),
            ),
        )
    )
    return run_validation(
        command=make_command(budget_amount=Decimal("1000.00")),
        itinerary=result.itinerary,
        report_id=_REPORT_ID,
        validated_at=_VALIDATED_AT,
        validation_inputs=inputs,
    )


def test_run_validation_exposes_canonical_assessments_in_report_order() -> None:
    run = _run()

    assert tuple(item.result for item in run.assessments) == run.report.rule_results
    assert run.context.itinerary is run.itinerary


def test_validator_marks_supported_duration_failure_repairable() -> None:
    report = _run().report
    duration = next(result for result in report.rule_results if result.rule_id == "VISIT_DURATION")

    assert duration.outcome is RuleOutcome.FAIL
    assert duration.reason_code == "VISIT_TOO_SHORT"
    assert duration.repairable is True


def test_validator_keeps_unsupported_budget_failure_unrepairable() -> None:
    run = _run(cost=Decimal("1100.00"))
    budget = next(result for result in run.report.rule_results if result.rule_id == "BUDGET_LIMIT")

    assert budget.outcome is RuleOutcome.FAIL
    assert budget.repairable is False


def test_validate_itinerary_records_caller_supplied_attempts_under_v5() -> None:
    itinerary = _run().itinerary
    before = "1" * 64
    after = "2" * 64
    attempt = RepairAttempt(
        attempt_index=1,
        triggering_rule_ids=("VISIT_DURATION",),
        action_codes=("CLAMP_VISIT_DURATION",),
        affected_dates=(itinerary.days[0].date,),
        affected_entity_refs=(f"activity:{itinerary.days[0].activities[0].activity_id}",),
        before_fingerprint=before,
        after_fingerprint=after,
        resulting_status=FeasibilityStatus.UNVERIFIED,
    )

    report = validate_itinerary(
        command=make_command(),
        itinerary=itinerary,
        report_id=_REPORT_ID,
        validated_at=_VALIDATED_AT,
        repair_attempts=(attempt,),
    )

    assert report.validator_version == "hard-validator-v5"
    assert report.repair_attempts == (attempt,)
