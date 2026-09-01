"""B5 Phase 5 — VISIT_DURATION canonical rule."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from plan_evaluation_support import make_command

from trip_agent.domain.shared import CHINA_TIME_ZONE
from trip_agent.feasibility.context import ValidationContext, build_budget_context
from trip_agent.feasibility.inputs import (
    ActivityLocator,
    ValidationInputs,
    VisitDurationBinding,
)
from trip_agent.feasibility.models import EvidenceState, RuleOutcome
from trip_agent.feasibility.rules.duration import assess_visit_duration
from trip_agent.planning.visit_duration import (
    DurationProfileSource,
    VisitDurationProfile,
)
from trip_agent.worker.contracts import (
    ActivityCoordinates,
    Itinerary,
    ItineraryActivity,
    ItineraryDay,
)


def _profile(
    *,
    min_minutes: int = 90,
    recommended_minutes: int = 150,
    max_minutes: int = 180,
    eligible: bool = False,
) -> VisitDurationProfile:
    return VisitDurationProfile(
        min_minutes=min_minutes,
        recommended_minutes=recommended_minutes,
        max_minutes=max_minutes,
        source=(
            DurationProfileSource.OFFICIAL_FACT
            if eligible
            else DurationProfileSource.CATEGORY_PROFILE
        ),
        source_ref="official:1" if eligible else "category:normal",
        confidence=0.9 if eligible else 0.5,
        profile_version="category-profile-v1",
        hard_constraint_eligible=eligible,
    )


def _activity(
    index: int,
    *,
    start_hour: int,
    duration_minutes: int,
    duration_seconds: int = 0,
    duration_microseconds: int = 0,
    kind: str = "ATTRACTION",
    naive: bool = False,
    poi: str = "POI-1",
) -> ItineraryActivity:
    tz = None if naive else CHINA_TIME_ZONE
    start = datetime(2026, 8, 1, start_hour, tzinfo=tz)
    return ItineraryActivity(
        activity_id=UUID(int=index + 1),
        title="A",
        start_time=start,
        end_time=start
        + timedelta(
            minutes=duration_minutes,
            seconds=duration_seconds,
            microseconds=duration_microseconds,
        ),
        estimated_cost=Decimal("0"),
        source="AMAP",
        provider_poi_id=poi,
        coordinates=ActivityCoordinates(longitude=Decimal("113.31"), latitude=Decimal("23.13")),
        address="addr",
        kind=kind,  # type: ignore[arg-type]
    )


def _ctx(
    *activities: ItineraryActivity,
    bindings: tuple[VisitDurationBinding, ...] = (),
) -> ValidationContext:
    command = make_command()
    itinerary = Itinerary(
        title="duration",
        days=(ItineraryDay(date=date(2026, 8, 1), activities=activities, transit_legs=()),),
        estimated_total_cost=Decimal("0"),
    )
    return ValidationContext(
        command=command,
        itinerary=itinerary,
        budget=build_budget_context(command, itinerary),
        validation_inputs=ValidationInputs(
            visit_duration_bindings=bindings,
            meal_projection_state=__import__(
                "trip_agent.feasibility.inputs", fromlist=["MealProjectionState"]
            ).MealProjectionState.UNAVAILABLE,
        ),
    )


def _binding(day: int, activity: int, profile: VisitDurationProfile) -> VisitDurationBinding:
    return VisitDurationBinding(
        activity=ActivityLocator(day_index=day, activity_index=activity),
        profile=profile,
    )


def test_no_applicable_activities_is_not_applicable() -> None:
    ctx = _ctx(_activity(0, start_hour=9, duration_minutes=60, kind="MEAL"))

    assessment = assess_visit_duration(ctx)

    assert assessment.result.outcome is RuleOutcome.NOT_APPLICABLE
    assert assessment.result.reason_code == "NO_DURATION_APPLICABLE_ACTIVITIES"


def test_missing_profile_is_unknown() -> None:
    ctx = _ctx(_activity(0, start_hour=9, duration_minutes=60))

    assessment = assess_visit_duration(ctx)

    assert assessment.result.outcome is RuleOutcome.UNKNOWN
    assert assessment.result.reason_code == "VISIT_DURATION_PROFILE_MISSING"


def test_ineligible_category_profile_is_unknown() -> None:
    ctx = _ctx(
        _activity(0, start_hour=9, duration_minutes=150),
        bindings=(_binding(0, 0, _profile()),),
    )

    assessment = assess_visit_duration(ctx)

    assert assessment.result.outcome is RuleOutcome.UNKNOWN
    assert assessment.result.reason_code == "VISIT_DURATION_UNVERIFIED"


def test_eligible_duration_within_bounds_passes() -> None:
    ctx = _ctx(
        _activity(0, start_hour=9, duration_minutes=150),
        bindings=(_binding(0, 0, _profile(eligible=True)),),
    )

    assessment = assess_visit_duration(ctx)

    assert assessment.result.outcome is RuleOutcome.PASS
    assert assessment.result.reason_code == "VISIT_DURATIONS_VERIFIED"


def test_eligible_duration_at_min_boundary_passes() -> None:
    ctx = _ctx(
        _activity(0, start_hour=9, duration_minutes=90),
        bindings=(_binding(0, 0, _profile(eligible=True)),),
    )

    assessment = assess_visit_duration(ctx)

    assert assessment.result.outcome is RuleOutcome.PASS


def test_eligible_duration_at_max_boundary_passes() -> None:
    ctx = _ctx(
        _activity(0, start_hour=9, duration_minutes=180),
        bindings=(_binding(0, 0, _profile(eligible=True)),),
    )

    assessment = assess_visit_duration(ctx)

    assert assessment.result.outcome is RuleOutcome.PASS


def test_eligible_duration_too_short_fails() -> None:
    ctx = _ctx(
        _activity(0, start_hour=9, duration_minutes=60),
        bindings=(_binding(0, 0, _profile(eligible=True)),),
    )

    assessment = assess_visit_duration(ctx)

    assert assessment.result.outcome is RuleOutcome.FAIL
    assert assessment.result.reason_code == "VISIT_TOO_SHORT"
    assert assessment.result.affected_dates == (date(2026, 8, 1),)
    assert assessment.result.affected_entity_refs == (
        "activity:00000000-0000-0000-0000-000000000001",
    )  # activity_id


def test_eligible_duration_too_long_fails() -> None:
    ctx = _ctx(
        _activity(0, start_hour=9, duration_minutes=240),
        bindings=(_binding(0, 0, _profile(eligible=True)),),
    )

    assessment = assess_visit_duration(ctx)

    assert assessment.result.outcome is RuleOutcome.FAIL
    assert assessment.result.reason_code == "VISIT_TOO_LONG"


def test_non_positive_duration_fails_short() -> None:
    ctx = _ctx(
        _activity(0, start_hour=9, duration_minutes=0),
        bindings=(_binding(0, 0, _profile(eligible=True)),),
    )

    assessment = assess_visit_duration(ctx)

    assert assessment.result.outcome is RuleOutcome.FAIL
    assert assessment.result.reason_code == "VISIT_TOO_SHORT"


def test_mixed_naive_time_is_unknown_not_crash() -> None:
    ctx = _ctx(
        _activity(0, start_hour=9, duration_minutes=150),
        bindings=(_binding(0, 0, _profile(eligible=True)),),
    )
    naive_activity = _activity(1, start_hour=10, duration_minutes=150, naive=True)
    itinerary = Itinerary(
        title="mixed",
        days=(
            ItineraryDay(
                date=date(2026, 8, 1),
                activities=(ctx.itinerary.days[0].activities[0], naive_activity),
                transit_legs=(),
            ),
        ),
        estimated_total_cost=Decimal("0"),
    )
    mixed_ctx = ValidationContext(
        command=ctx.command,
        itinerary=itinerary,
        budget=ctx.budget,
        validation_inputs=ValidationInputs(
            visit_duration_bindings=(
                _binding(0, 0, _profile(eligible=True)),
                _binding(0, 1, _profile(eligible=True)),
            ),
            meal_projection_state=__import__(
                "trip_agent.feasibility.inputs", fromlist=["MealProjectionState"]
            ).MealProjectionState.UNAVAILABLE,
        ),
    )

    assessment = assess_visit_duration(mixed_ctx)

    assert assessment.result.outcome is RuleOutcome.UNKNOWN
    assert assessment.result.reason_code == "VISIT_DURATION_UNVERIFIED"


def test_fail_precedes_unknown() -> None:
    ctx = _ctx(
        _activity(0, start_hour=9, duration_minutes=60),
        _activity(1, start_hour=12, duration_minutes=150),
        bindings=(
            _binding(0, 0, _profile(eligible=True)),
            _binding(0, 1, _profile()),
        ),
    )

    assessment = assess_visit_duration(ctx)

    assert assessment.result.outcome is RuleOutcome.FAIL
    assert assessment.result.reason_code == "VISIT_TOO_SHORT"


def test_evidence_refs_reflect_profile_eligibility() -> None:
    ctx = _ctx(
        _activity(0, start_hour=9, duration_minutes=150),
        bindings=(_binding(0, 0, _profile(eligible=True)),),
    )

    assessment = assess_visit_duration(ctx)

    refs = assessment.result.evidence_refs
    assert len(refs) == 1
    assert refs[0].evidence_type == "VISIT_DURATION"
    assert refs[0].evidence_id == "official:1"
    assert refs[0].state is EvidenceState.VERIFIED
    assert refs[0].hard_constraint_eligible is True


def test_category_profile_evidence_is_unknown_state() -> None:
    ctx = _ctx(
        _activity(0, start_hour=9, duration_minutes=150),
        bindings=(_binding(0, 0, _profile()),),
    )

    assessment = assess_visit_duration(ctx)

    refs = assessment.result.evidence_refs
    assert refs[0].state is EvidenceState.UNKNOWN
    assert refs[0].hard_constraint_eligible is False


def test_does_not_mutate_inputs() -> None:
    profile = _profile(eligible=True)
    activity = _activity(0, start_hour=9, duration_minutes=150)
    ctx = _ctx(activity, bindings=(_binding(0, 0, profile),))
    before = ctx.itinerary.model_dump_json(by_alias=True)

    assess_visit_duration(ctx)

    assert ctx.itinerary.model_dump_json(by_alias=True) == before
    assert profile.min_minutes == 90


# ── B5.1 RED 2: exact duration boundaries ──────────────────────────────────


def test_duration_one_second_over_max_fails() -> None:
    ctx = _ctx(
        _activity(0, start_hour=9, duration_minutes=180, duration_seconds=1),
        bindings=(_binding(0, 0, _profile(eligible=True)),),
    )

    assessment = assess_visit_duration(ctx)

    assert assessment.result.outcome is RuleOutcome.FAIL
    assert assessment.result.reason_code == "VISIT_TOO_LONG"


def test_duration_one_second_under_min_fails() -> None:
    ctx = _ctx(
        _activity(0, start_hour=9, duration_minutes=89, duration_seconds=59),
        bindings=(_binding(0, 0, _profile(eligible=True)),),
    )

    assessment = assess_visit_duration(ctx)

    assert assessment.result.outcome is RuleOutcome.FAIL
    assert assessment.result.reason_code == "VISIT_TOO_SHORT"


def test_duration_exactly_at_max_passes() -> None:
    ctx = _ctx(
        _activity(0, start_hour=9, duration_minutes=180),
        bindings=(_binding(0, 0, _profile(eligible=True)),),
    )

    assessment = assess_visit_duration(ctx)

    assert assessment.result.outcome is RuleOutcome.PASS


def test_duration_microsecond_over_max_fails() -> None:
    ctx = _ctx(
        _activity(0, start_hour=9, duration_minutes=180, duration_microseconds=1),
        bindings=(_binding(0, 0, _profile(eligible=True)),),
    )

    assessment = assess_visit_duration(ctx)

    assert assessment.result.outcome is RuleOutcome.FAIL
    assert assessment.result.reason_code == "VISIT_TOO_LONG"
