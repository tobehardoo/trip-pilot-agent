from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from plan_evaluation_support import make_command

from trip_agent.domain.shared import CHINA_TIME_ZONE, ActivityKind
from trip_agent.feasibility.inputs import (
    ActivityLocator,
    MealPlacementBinding,
    MealProjectionState,
    MealWindowType,
    OpeningHoursBinding,
    ValidationInputs,
    VisitDurationBinding,
)
from trip_agent.feasibility.repair.catalog import RepairActionCode
from trip_agent.feasibility.repair.engine import (
    apply_repair_plan,
    plan_repairs,
)
from trip_agent.feasibility.validator import run_validation
from trip_agent.guide_intelligence.opening_evidence import OpeningHoursEvidence
from trip_agent.guide_intelligence.opening_hours import parse_opening_text
from trip_agent.planning.visit_duration import (
    DurationProfileSource,
    VisitDurationProfile,
)
from trip_agent.worker.contracts import (
    ActivityCoordinates,
    Itinerary,
    ItineraryActivity,
    ItineraryDay,
    TransitLeg,
)

_REPORT_ID = UUID("4d9b7e0a-3c2f-4a1b-9e8d-7f6e5d4c3b2a")
_VALIDATED_AT = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)
_DAY = date(2026, 8, 1)


def _activity(
    index: int,
    *,
    poi: str,
    title: str,
    start_hour: int,
    start_minute: int = 0,
    duration_minutes: int = 60,
    kind: ActivityKind = "ATTRACTION",
    time_fixed: bool = False,
) -> ItineraryActivity:
    start = datetime(
        2026,
        8,
        1,
        start_hour,
        start_minute,
        tzinfo=CHINA_TIME_ZONE,
    )
    return ItineraryActivity(
        activity_id=UUID(int=index + 1),
        title=title,
        start_time=start,
        end_time=start + timedelta(minutes=duration_minutes),
        estimated_cost=Decimal("10.00"),
        source="AMAP",
        provider_poi_id=poi,
        coordinates=ActivityCoordinates(
            longitude=Decimal("113.31") + Decimal(index) / 100,
            latitude=Decimal("23.13"),
        ),
        address=f"address-{index}",
        kind=kind,
        time_fixed=time_fixed,
    )


def _leg(index: int) -> TransitLeg:
    return TransitLeg(
        transit_id=UUID(int=100 + index),
        from_activity_index=index,
        to_activity_index=index + 1,
        mode="WALKING",
        distance_meters=100,
        duration_seconds=300,
        provider="AMAP",
        estimated=False,
        polyline=(ActivityCoordinates(longitude=Decimal("113.31"), latitude=Decimal("23.13")),),
    )


def _opening(poi: str, raw: str = "09:00-18:00") -> OpeningHoursEvidence:
    return OpeningHoursEvidence(
        kind="OPENING_HOURS",
        poi_key=poi,
        parsed_hours=parse_opening_text(raw),
        raw=raw,
        effective_date=None,
        source_ref=f"official:{poi}",
        reliability_level="OFFICIAL",
        source_reviewed=True,
        hard_constraint_eligible=True,
        confidence=0.9,
        checked_at=datetime(2026, 8, 1, tzinfo=UTC),
        expires_at=datetime(2026, 8, 31, tzinfo=UTC),
    )


def _profile(*, min_minutes: int = 45, max_minutes: int = 120) -> VisitDurationProfile:
    return VisitDurationProfile(
        min_minutes=min_minutes,
        recommended_minutes=90,
        max_minutes=max_minutes,
        source=DurationProfileSource.OFFICIAL_FACT,
        source_ref="official:duration",
        confidence=0.9,
        profile_version="official-v1",
        hard_constraint_eligible=True,
    )


def _run(
    activities: tuple[ItineraryActivity, ...],
    *,
    inputs: ValidationInputs,
    transit_legs: tuple[TransitLeg, ...] = (),
    meal_windows: tuple[dict[str, object], ...] = (),
    must_visit_places: tuple[str, ...] = (),
):
    itinerary = Itinerary(
        title="repair candidate",
        days=(
            ItineraryDay(
                date=_DAY,
                activities=activities,
                transit_legs=transit_legs,
            ),
        ),
        estimated_total_cost=sum(
            (activity.estimated_cost for activity in activities),
            start=Decimal("0"),
        ),
    )
    command = make_command(
        budget_amount=Decimal("1000.00"),
        meal_windows=meal_windows,
        must_visit_places=must_visit_places,
    )
    return run_validation(
        command=command,
        itinerary=itinerary,
        report_id=_REPORT_ID,
        validated_at=_VALIDATED_AT,
        validation_inputs=inputs,
    )


def _inputs_for_activity(
    activity: ItineraryActivity,
    *,
    opening: str = "09:00-18:00",
    profile: VisitDurationProfile | None = None,
) -> ValidationInputs:
    assert activity.provider_poi_id is not None
    return ValidationInputs(
        opening_hours_bindings=(
            OpeningHoursBinding(
                activity=ActivityLocator(0, 0),
                poi_key=activity.provider_poi_id,
                evidences=(_opening(activity.provider_poi_id, opening),),
            ),
        ),
        visit_duration_bindings=(
            VisitDurationBinding(
                activity=ActivityLocator(0, 0),
                profile=profile or _profile(),
            ),
        ),
    )


def test_duration_clamp_creates_new_candidate_and_preserves_input() -> None:
    activity = _activity(
        0,
        poi="POI-1",
        title="museum",
        start_hour=10,
        duration_minutes=20,
    )
    run = _run((activity,), inputs=_inputs_for_activity(activity))
    before = run.itinerary.model_dump_json(by_alias=True)

    plan = plan_repairs(run, attempt_index=1)
    assert plan is not None
    assert tuple(action.code for action in plan.actions) == (RepairActionCode.CLAMP_VISIT_DURATION,)

    applied = apply_repair_plan(run, plan)

    repaired = applied.candidate.itinerary.days[0].activities[0]
    assert repaired.start_time == activity.start_time
    assert repaired.end_time == activity.start_time + timedelta(minutes=45)
    assert run.itinerary.model_dump_json(by_alias=True) == before
    assert applied.provider_dates == ()


def test_time_only_repair_preserves_declared_total_cost() -> None:
    activity = _activity(
        0,
        poi="POI-1",
        title="museum",
        start_hour=10,
        duration_minutes=20,
    )
    initial = _run((activity,), inputs=_inputs_for_activity(activity))
    itinerary = initial.itinerary.model_copy(update={"estimated_total_cost": Decimal("999.00")})
    run = run_validation(
        command=initial.context.command,
        itinerary=itinerary,
        report_id=_REPORT_ID,
        validated_at=_VALIDATED_AT,
        validation_inputs=initial.context.validation_inputs,
    )
    plan = plan_repairs(run, attempt_index=1)
    assert plan is not None

    applied = apply_repair_plan(run, plan)

    assert applied.candidate.itinerary.estimated_total_cost == Decimal("999.00")


def test_duration_repair_does_not_extend_activity_into_another_day() -> None:
    activity = _activity(
        0,
        poi="POI-1",
        title="late museum",
        start_hour=23,
        start_minute=50,
        duration_minutes=9,
    )
    inputs = ValidationInputs(
        visit_duration_bindings=(
            VisitDurationBinding(
                activity=ActivityLocator(0, 0),
                profile=_profile(min_minutes=45),
            ),
        )
    )
    run = _run((activity,), inputs=inputs)
    plan = plan_repairs(run, attempt_index=1)
    assert plan is not None

    applied = apply_repair_plan(run, plan)

    assert applied.candidate.itinerary is run.itinerary


def test_opening_shift_uses_verified_window_and_revalidates() -> None:
    activity = _activity(
        0,
        poi="POI-1",
        title="museum",
        start_hour=19,
    )
    run = _run((activity,), inputs=_inputs_for_activity(activity))

    plan = plan_repairs(run, attempt_index=1)
    assert plan is not None
    assert plan.actions[0].code is RepairActionCode.SHIFT_ACTIVITY_TO_OPENING_WINDOW

    applied = apply_repair_plan(run, plan)
    repaired = applied.candidate.itinerary.days[0].activities[0]

    assert repaired.start_time.astimezone(CHINA_TIME_ZONE).hour == 9
    assert repaired.end_time - repaired.start_time == timedelta(hours=1)


def test_opening_shift_uses_earliest_legal_time_after_previous_activity() -> None:
    previous = _activity(0, poi="POI-0", title="previous", start_hour=9)
    target = _activity(1, poi="POI-1", title="museum", start_hour=19)
    inputs = OpeningHoursBinding(
        activity=ActivityLocator(0, 1),
        poi_key="POI-1",
        evidences=(_opening("POI-1"),),
    )
    run = _run(
        (previous, target),
        inputs=ValidationInputs(opening_hours_bindings=(inputs,)),
        transit_legs=(_leg(0),),
    )

    plan = plan_repairs(run, attempt_index=1)
    assert plan is not None
    repaired = apply_repair_plan(run, plan).candidate.itinerary.days[0].activities[1]

    assert repaired.start_time == previous.end_time + timedelta(minutes=5)
    assert repaired.end_time == repaired.start_time + timedelta(hours=1)


def test_last_entry_shift_and_meal_shift_are_explicit_actions() -> None:
    visit = _activity(
        0,
        poi="POI-1",
        title="museum",
        start_hour=17,
        start_minute=30,
        duration_minutes=30,
    )
    visit_run = _run(
        (visit,),
        inputs=_inputs_for_activity(
            visit,
            opening="09:00-18:00 (17:00停止入场)",
            profile=_profile(min_minutes=30),
        ),
    )
    visit_plan = plan_repairs(visit_run, attempt_index=1)
    assert visit_plan is not None
    assert visit_plan.actions[0].code is RepairActionCode.SHIFT_ACTIVITY_BEFORE_LAST_ENTRY
    visit_result = apply_repair_plan(visit_run, visit_plan)
    assert (
        visit_result.candidate.itinerary.days[0]
        .activities[0]
        .start_time.astimezone(CHINA_TIME_ZONE)
        .time()
        <= datetime(2026, 8, 1, 17, tzinfo=CHINA_TIME_ZONE).time()
    )

    meal = _activity(
        1,
        poi="MEAL-1",
        title="lunch",
        start_hour=13,
        start_minute=30,
        duration_minutes=30,
        kind="MEAL",
    )
    meal_inputs = ValidationInputs(
        meal_placement_bindings=(
            MealPlacementBinding(
                activity=ActivityLocator(0, 0),
                meal_type=MealWindowType.LUNCH,
            ),
        ),
        meal_projection_state=MealProjectionState.COMPLETE,
    )
    meal_run = _run(
        (meal,),
        inputs=meal_inputs,
        meal_windows=({"mealType": "LUNCH", "startTime": "12:00", "endTime": "13:00"},),
    )
    meal_plan = plan_repairs(meal_run, attempt_index=1)
    assert meal_plan is not None
    assert meal_plan.actions[0].code is RepairActionCode.SHIFT_MEAL_TO_WINDOW
    meal_result = apply_repair_plan(meal_run, meal_plan)
    assert (
        meal_result.candidate.itinerary.days[0]
        .activities[0]
        .start_time.astimezone(CHINA_TIME_ZONE)
        .hour
        == 12
    )


def test_meal_shift_uses_earliest_legal_time_after_previous_activity() -> None:
    previous = _activity(
        0,
        poi="POI-0",
        title="previous",
        start_hour=11,
        duration_minutes=65,
    )
    meal = _activity(
        1,
        poi="MEAL-1",
        title="lunch",
        start_hour=13,
        start_minute=30,
        duration_minutes=30,
        kind="MEAL",
    )
    run = _run(
        (previous, meal),
        inputs=ValidationInputs(
            meal_placement_bindings=(
                MealPlacementBinding(
                    activity=ActivityLocator(0, 1),
                    meal_type=MealWindowType.LUNCH,
                ),
            ),
            meal_projection_state=MealProjectionState.COMPLETE,
        ),
        transit_legs=(_leg(0),),
        meal_windows=({"mealType": "LUNCH", "startTime": "12:00", "endTime": "13:00"},),
    )

    plan = plan_repairs(run, attempt_index=1)
    assert plan is not None
    repaired = apply_repair_plan(run, plan).candidate.itinerary.days[0].activities[1]

    assert repaired.start_time == previous.end_time + timedelta(minutes=5)


def test_duplicate_removal_is_optional_only_and_requests_route_refresh() -> None:
    first = _activity(0, poi="POI-1", title="museum", start_hour=9)
    duplicate = _activity(1, poi="POI-1", title="museum again", start_hour=11)
    last = _activity(2, poi="POI-2", title="park", start_hour=13)
    inputs = ValidationInputs(
        opening_hours_bindings=tuple(
            OpeningHoursBinding(
                activity=ActivityLocator(0, index),
                poi_key=activity.provider_poi_id or "",
                evidences=(_opening(activity.provider_poi_id or ""),),
            )
            for index, activity in enumerate((first, duplicate, last))
        ),
        visit_duration_bindings=tuple(
            VisitDurationBinding(
                activity=ActivityLocator(0, index),
                profile=_profile(),
            )
            for index in range(3)
        ),
    )
    run = _run(
        (first, duplicate, last),
        inputs=inputs,
        transit_legs=(_leg(0), _leg(1)),
    )

    plan = plan_repairs(run, attempt_index=1)
    assert plan is not None
    assert tuple(action.code for action in plan.actions) == (
        RepairActionCode.REMOVE_DUPLICATE_OPTIONAL_POI,
    )
    applied = apply_repair_plan(run, plan)

    assert tuple(
        activity.provider_poi_id for activity in applied.candidate.itinerary.days[0].activities
    ) == ("POI-1", "POI-2")
    assert applied.provider_dates == (_DAY,)
    assert applied.candidate.validation_inputs is not None
    assert tuple(
        binding.activity.activity_index
        for binding in applied.candidate.validation_inputs.opening_hours_bindings
    ) == (0, 1)


def test_duplicate_removal_subtracts_only_removed_activity_cost() -> None:
    first = _activity(0, poi="POI-1", title="museum", start_hour=9)
    duplicate = _activity(1, poi="POI-1", title="museum again", start_hour=11)
    last = _activity(2, poi="POI-2", title="park", start_hour=13)
    initial = _run(
        (first, duplicate, last),
        inputs=ValidationInputs(),
        transit_legs=(_leg(0), _leg(1)),
    )
    itinerary = initial.itinerary.model_copy(update={"estimated_total_cost": Decimal("130.00")})
    run = run_validation(
        command=initial.context.command,
        itinerary=itinerary,
        report_id=_REPORT_ID,
        validated_at=_VALIDATED_AT,
        validation_inputs=initial.context.validation_inputs,
    )
    plan = plan_repairs(run, attempt_index=1)
    assert plan is not None

    applied = apply_repair_plan(run, plan)

    assert applied.candidate.itinerary.estimated_total_cost == Decimal("120.00")


def test_route_missing_requests_provider_without_mutating_local_candidate() -> None:
    first = _activity(0, poi="POI-1", title="museum", start_hour=9)
    second = _activity(1, poi="POI-2", title="park", start_hour=11)
    run = _run((first, second), inputs=ValidationInputs(), transit_legs=())

    plan = plan_repairs(run, attempt_index=1)
    assert plan is not None
    assert RepairActionCode.REFRESH_TRANSIT_LEGS in {action.code for action in plan.actions}
    applied = apply_repair_plan(run, plan)

    assert applied.candidate.itinerary is run.itinerary
    assert applied.provider_dates == (_DAY,)


def test_provider_dates_are_bounded_to_three_in_stable_order() -> None:
    days = []
    for day_offset in range(4):
        first = _activity(
            day_offset * 2,
            poi=f"POI-{day_offset}-A",
            title="first",
            start_hour=9,
        ).model_copy(
            update={
                "start_time": datetime(2026, 8, day_offset + 1, 9, tzinfo=CHINA_TIME_ZONE),
                "end_time": datetime(2026, 8, day_offset + 1, 10, tzinfo=CHINA_TIME_ZONE),
            }
        )
        second = _activity(
            day_offset * 2 + 1,
            poi=f"POI-{day_offset}-B",
            title="second",
            start_hour=11,
        ).model_copy(
            update={
                "start_time": datetime(2026, 8, day_offset + 1, 11, tzinfo=CHINA_TIME_ZONE),
                "end_time": datetime(2026, 8, day_offset + 1, 12, tzinfo=CHINA_TIME_ZONE),
            }
        )
        days.append(
            ItineraryDay(
                date=date(2026, 8, day_offset + 1),
                activities=(first, second),
                transit_legs=(),
            )
        )
    itinerary = Itinerary(
        title="four days",
        days=tuple(days),
        estimated_total_cost=Decimal("80.00"),
    )
    run = run_validation(
        command=make_command(),
        itinerary=itinerary,
        report_id=_REPORT_ID,
        validated_at=_VALIDATED_AT,
        validation_inputs=ValidationInputs(),
    )

    plan = plan_repairs(run, attempt_index=1)
    assert plan is not None
    assert tuple(sorted({action.affected_date for action in plan.actions})) == (
        date(2026, 8, 1),
        date(2026, 8, 2),
        date(2026, 8, 3),
    )
    applied = apply_repair_plan(run, plan)

    assert applied.provider_dates == (
        date(2026, 8, 1),
        date(2026, 8, 2),
        date(2026, 8, 3),
    )


def test_time_fixed_activity_is_not_a_legal_repair_target() -> None:
    activity = _activity(
        0,
        poi="POI-1",
        title="fixed museum",
        start_hour=19,
        time_fixed=True,
    )
    run = _run((activity,), inputs=_inputs_for_activity(activity))

    assert plan_repairs(run, attempt_index=1) is None
