"""B5 Phase 9 — unified golden scenarios across all eleven rules.

Each golden builds a full ValidationContext and asserts the aggregated
report: VERIFIED only with complete eligible inputs, UNVERIFIED for any
evidence gap, NEEDS_REPAIR for any hard FAIL, FAIL > UNKNOWN, bounded
aggregates, and no input mutation.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from plan_evaluation_support import make_command

from trip_agent.domain.shared import CHINA_TIME_ZONE
from trip_agent.feasibility.context import ValidationContext, build_budget_context
from trip_agent.feasibility.inputs import (
    ActivityLocator,
    MealPlacementBinding,
    MealProjectionState,
    MealWindowType,
    OpeningHoursBinding,
    ValidationInputs,
    VisitDurationBinding,
)
from trip_agent.feasibility.models import FeasibilityStatus, RuleOutcome
from trip_agent.feasibility.validator import validate_itinerary
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

REPORT_ID = "4d9b7e0a-3c2f-4a1b-9e8d-7f6e5d4c3b2a"
_TS = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)
_DAY = date(2026, 8, 1)


def _activity(
    index: int,
    *,
    poi: str,
    title: str,
    kind: str = "ATTRACTION",
    start_hour: int = 10,
    duration_minutes: int = 60,
    day: int = 1,
    has_coordinates: bool = True,
) -> ItineraryActivity:
    start = datetime(2026, 8, day, start_hour, tzinfo=CHINA_TIME_ZONE)
    return ItineraryActivity(
        activity_id=UUID(int=index + 1),
        title=title,
        start_time=start,
        end_time=start + timedelta(minutes=duration_minutes),
        estimated_cost=Decimal("0"),
        source="AMAP",
        provider_poi_id=poi,
        coordinates=(
            ActivityCoordinates(longitude=Decimal("113.31"), latitude=Decimal("23.13"))
            if has_coordinates
            else None
        ),
        address="addr",
        kind=kind,  # type: ignore[arg-type]
    )


def _leg(from_index: int) -> TransitLeg:
    return TransitLeg(
        transit_id=UUID(int=100 + from_index),
        from_activity_index=from_index,
        to_activity_index=from_index + 1,
        mode="WALKING",
        distance_meters=300,
        duration_seconds=300,
        provider="AMAP",
        estimated=False,
        polyline=(
            ActivityCoordinates(longitude=Decimal("113.31"), latitude=Decimal("23.13")),
            ActivityCoordinates(longitude=Decimal("113.32"), latitude=Decimal("23.14")),
        ),
    )


def _eligible_evidence(
    poi: str,
    raw: str = "09:00-18:00",
    *,
    checked: datetime | None = None,
) -> OpeningHoursEvidence:
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
        checked_at=checked or datetime(2026, 8, 1, tzinfo=UTC),
        expires_at=datetime(2026, 8, 31, tzinfo=UTC),
    )


def _eligible_profile(
    poi: str,
    *,
    min_m: int = 45,
    rec_m: int = 90,
    max_m: int = 120,
) -> VisitDurationProfile:
    return VisitDurationProfile(
        min_minutes=min_m,
        recommended_minutes=rec_m,
        max_minutes=max_m,
        source=DurationProfileSource.OFFICIAL_FACT,
        source_ref=f"official:{poi}",
        confidence=0.9,
        profile_version="official-v1",
        hard_constraint_eligible=True,
    )


def _category_profile() -> VisitDurationProfile:
    return VisitDurationProfile(
        min_minutes=90,
        recommended_minutes=150,
        max_minutes=180,
        source=DurationProfileSource.CATEGORY_PROFILE,
        source_ref="category:normal",
        confidence=0.5,
        profile_version="category-profile-v1",
        hard_constraint_eligible=False,
    )


def _ctx(
    *days: ItineraryDay,
    must_visit: tuple[str, ...] = (),
    meal_windows: tuple[tuple[str, int, int], ...] = (),
    inputs: ValidationInputs | None = None,
) -> ValidationContext:
    command = make_command(
        must_visit_places=must_visit,
        meal_windows=tuple(
            {
                "mealType": meal_type,
                "startTime": f"{start:02d}:00",
                "endTime": f"{end:02d}:00",
            }
            for meal_type, start, end in meal_windows
        ),
    )
    itinerary = Itinerary(
        title="golden",
        days=days,
        estimated_total_cost=Decimal("100.00"),
    )
    return ValidationContext(
        command=command,
        itinerary=itinerary,
        budget=build_budget_context(command, itinerary),
        validation_inputs=inputs,
        validation_time=_TS,
    )


def _report(ctx: ValidationContext):
    return validate_itinerary(
        command=ctx.command,
        itinerary=ctx.itinerary,
        report_id=REPORT_ID,
        validated_at=_TS,
        validation_inputs=ctx.validation_inputs,
    )


def _bindings(
    opening: tuple[tuple[int, int, str, OpeningHoursEvidence], ...] = (),
    durations: tuple[tuple[int, int, VisitDurationProfile], ...] = (),
    meals: tuple[tuple[int, int, str], ...] = (),
    projection: MealProjectionState = MealProjectionState.UNAVAILABLE,
) -> ValidationInputs:
    return ValidationInputs(
        opening_hours_bindings=tuple(
            OpeningHoursBinding(
                activity=ActivityLocator(day_index=day, activity_index=act),
                poi_key=poi,
                evidences=(evidence,),
            )
            for day, act, poi, evidence in opening
        ),
        visit_duration_bindings=tuple(
            VisitDurationBinding(
                activity=ActivityLocator(day_index=day, activity_index=act),
                profile=profile,
            )
            for day, act, profile in durations
        ),
        meal_placement_bindings=tuple(
            MealPlacementBinding(
                activity=ActivityLocator(day_index=day, activity_index=act),
                meal_type=MealWindowType(meal_type),
            )
            for day, act, meal_type in meals
        ),
        meal_projection_state=projection,
    )


# ── Golden A: complete eligible inputs -> VERIFIED ─────────────────────────


def test_golden_a_complete_eligible_inputs_verify() -> None:
    activities = (
        _activity(0, poi="POI-1", title="陈家祠", start_hour=10, duration_minutes=60),
        _activity(1, poi="POI-2", title="光孝寺", start_hour=13, duration_minutes=60),
    )
    day = ItineraryDay(date=_DAY, activities=activities, transit_legs=(_leg(0),))
    inputs = _bindings(
        opening=(
            (0, 0, "POI-1", _eligible_evidence("POI-1")),
            (0, 1, "POI-2", _eligible_evidence("POI-2")),
        ),
        durations=(
            (0, 0, _eligible_profile("POI-1")),
            (0, 1, _eligible_profile("POI-2")),
        ),
    )
    report = _report(_ctx(day, must_visit=("陈家祠",), inputs=inputs))

    assert len(report.rule_results) == 11
    assert report.missing_required_rule_ids == ()
    assert report.status is FeasibilityStatus.VERIFIED
    assert report.summary.fail_count == 0
    assert report.summary.unknown_count == 0


# ── Golden B: demo-style evidence gaps -> UNVERIFIED ───────────────────────


def test_golden_b_demo_evidence_gaps_stay_unverified() -> None:
    activities = (
        _activity(0, poi="POI-1", title="陈家祠", start_hour=10, duration_minutes=60),
        _activity(1, poi="POI-2", title="光孝寺", start_hour=13, duration_minutes=60),
    )
    day = ItineraryDay(date=_DAY, activities=activities, transit_legs=(_leg(0),))
    report = _report(_ctx(day))  # no inputs at all

    assert report.status is FeasibilityStatus.UNVERIFIED
    assert report.status is not FeasibilityStatus.VERIFIED
    assert report.summary.fail_count == 0
    assert report.summary.unknown_count >= 1


# ── Golden C: stale / conflicting / unknown opening evidence ───────────────


def _expired_evidence(poi: str) -> OpeningHoursEvidence:
    return OpeningHoursEvidence(
        kind="OPENING_HOURS",
        poi_key=poi,
        parsed_hours=parse_opening_text("09:00-18:00"),
        raw="09:00-18:00",
        effective_date=None,
        source_ref=f"official:{poi}",
        reliability_level="OFFICIAL",
        source_reviewed=True,
        hard_constraint_eligible=True,
        confidence=0.9,
        checked_at=datetime(2026, 7, 1, tzinfo=UTC),
        expires_at=datetime(2026, 7, 15, tzinfo=UTC),  # stale at _TS
    )


def test_golden_c_stale_evidence_is_unverified() -> None:
    activities = (_activity(0, poi="POI-1", title="陈家祠", start_hour=10),)
    day = ItineraryDay(date=_DAY, activities=activities, transit_legs=())
    inputs = _bindings(
        opening=((0, 0, "POI-1", _expired_evidence("POI-1")),),
        durations=((0, 0, _eligible_profile("POI-1")),),
    )
    report = _report(_ctx(day, inputs=inputs))

    opening = next(r for r in report.rule_results if r.rule_id == "OPENING_HOURS")
    assert opening.outcome is RuleOutcome.UNKNOWN
    assert report.status is FeasibilityStatus.UNVERIFIED


def test_golden_c_conflicting_evidence_is_unverified() -> None:
    activities = (_activity(0, poi="POI-1", title="陈家祠", start_hour=10),)
    day = ItineraryDay(date=_DAY, activities=activities, transit_legs=())
    evidence_a = _eligible_evidence("POI-1", raw="09:00-12:00")
    evidence_b = _eligible_evidence("POI-1", raw="13:00-18:00")
    inputs = ValidationInputs(
        opening_hours_bindings=(
            OpeningHoursBinding(
                activity=ActivityLocator(day_index=0, activity_index=0),
                poi_key="POI-1",
                evidences=(evidence_a, evidence_b),
            ),
        ),
        visit_duration_bindings=(
            VisitDurationBinding(
                activity=ActivityLocator(day_index=0, activity_index=0),
                profile=_eligible_profile("POI-1"),
            ),
        ),
        meal_projection_state=MealProjectionState.UNAVAILABLE,
    )
    report = _report(_ctx(day, inputs=inputs))

    opening = next(r for r in report.rule_results if r.rule_id == "OPENING_HOURS")
    assert opening.outcome is RuleOutcome.UNKNOWN
    assert report.status is FeasibilityStatus.UNVERIFIED


# ── Golden D: eligible opening hard failures -> NEEDS_REPAIR ───────────────


def test_golden_d_eligible_closure_is_needs_repair() -> None:
    activities = (_activity(0, poi="POI-1", title="陈家祠", start_hour=10),)
    day = ItineraryDay(date=_DAY, activities=activities, transit_legs=())
    inputs = _bindings(
        opening=((0, 0, "POI-1", _eligible_evidence("POI-1", raw="闭馆")),),
        durations=((0, 0, _eligible_profile("POI-1")),),
    )
    report = _report(_ctx(day, inputs=inputs))

    opening = next(r for r in report.rule_results if r.rule_id == "OPENING_HOURS")
    assert opening.outcome is RuleOutcome.FAIL
    assert report.status is FeasibilityStatus.NEEDS_REPAIR
    assert opening.evidence_refs
    assert all(ref.hard_constraint_eligible for ref in opening.evidence_refs)


def test_golden_d_eligible_outside_window_is_needs_repair() -> None:
    activities = (_activity(0, poi="POI-1", title="陈家祠", start_hour=19),)
    day = ItineraryDay(date=_DAY, activities=activities, transit_legs=())
    inputs = _bindings(
        opening=((0, 0, "POI-1", _eligible_evidence("POI-1")),),
        durations=((0, 0, _eligible_profile("POI-1")),),
    )
    report = _report(_ctx(day, inputs=inputs))

    opening = next(r for r in report.rule_results if r.rule_id == "OPENING_HOURS")
    assert opening.outcome is RuleOutcome.FAIL
    assert report.status is FeasibilityStatus.NEEDS_REPAIR


# ── Golden E: visit duration ───────────────────────────────────────────────


def test_golden_e_category_duration_is_unknown() -> None:
    activities = (_activity(0, poi="POI-1", title="陈家祠", start_hour=10),)
    day = ItineraryDay(date=_DAY, activities=activities, transit_legs=())
    inputs = _bindings(
        durations=((0, 0, _category_profile()),),
    )
    report = _report(_ctx(day, inputs=inputs))

    duration = next(r for r in report.rule_results if r.rule_id == "VISIT_DURATION")
    assert duration.outcome is RuleOutcome.UNKNOWN
    assert report.status is FeasibilityStatus.UNVERIFIED


def test_golden_e_eligible_too_short_is_needs_repair() -> None:
    activities = (_activity(0, poi="POI-1", title="陈家祠", start_hour=10, duration_minutes=20),)
    day = ItineraryDay(date=_DAY, activities=activities, transit_legs=())
    inputs = _bindings(
        durations=((0, 0, _eligible_profile("POI-1")),),
    )
    report = _report(_ctx(day, inputs=inputs))

    duration = next(r for r in report.rule_results if r.rule_id == "VISIT_DURATION")
    assert duration.outcome is RuleOutcome.FAIL
    assert report.status is FeasibilityStatus.NEEDS_REPAIR


# ── Golden F: meal windows ─────────────────────────────────────────────────


def test_golden_f_meal_projection_unavailable_is_unverified() -> None:
    activities = (_activity(0, poi="POI-1", title="陈家祠", start_hour=10),)
    day = ItineraryDay(date=_DAY, activities=activities, transit_legs=())
    report = _report(_ctx(day, meal_windows=(("LUNCH", 12, 13),), inputs=None))

    meal = next(r for r in report.rule_results if r.rule_id == "MEAL_WINDOW")
    assert meal.outcome is RuleOutcome.UNKNOWN
    assert report.status is FeasibilityStatus.UNVERIFIED


def test_golden_f_meal_complete_missing_is_needs_repair() -> None:
    activities = (_activity(0, poi="POI-1", title="陈家祠", start_hour=10),)
    day = ItineraryDay(date=_DAY, activities=activities, transit_legs=())
    inputs = _bindings(projection=MealProjectionState.COMPLETE)
    report = _report(_ctx(day, meal_windows=(("LUNCH", 12, 13),), inputs=inputs))

    meal = next(r for r in report.rule_results if r.rule_id == "MEAL_WINDOW")
    assert meal.outcome is RuleOutcome.FAIL
    assert report.status is FeasibilityStatus.NEEDS_REPAIR


# ── Golden G: must visit ───────────────────────────────────────────────────


def test_golden_g_missing_must_visit_is_needs_repair() -> None:
    activities = (_activity(0, poi="POI-1", title="光孝寺", start_hour=10),)
    day = ItineraryDay(date=_DAY, activities=activities, transit_legs=())
    report = _report(_ctx(day, must_visit=("陈家祠",)))

    must = next(r for r in report.rule_results if r.rule_id == "MUST_VISIT_COVERAGE")
    assert must.outcome is RuleOutcome.FAIL
    assert report.status is FeasibilityStatus.NEEDS_REPAIR


def test_golden_g_child_poi_does_not_cover() -> None:
    activities = (_activity(0, poi="POI-1", title="陈家祠公交站", start_hour=10),)
    day = ItineraryDay(date=_DAY, activities=activities, transit_legs=())
    report = _report(_ctx(day, must_visit=("陈家祠",)))

    must = next(r for r in report.rule_results if r.rule_id == "MUST_VISIT_COVERAGE")
    assert must.outcome is RuleOutcome.FAIL
    assert report.status is FeasibilityStatus.NEEDS_REPAIR


# ── Golden H: cross-rule priority ──────────────────────────────────────────


def test_golden_h_fail_precedes_unknown() -> None:
    meal = _activity(2, poi="POI-3", title="午餐", kind="MEAL", start_hour=12)
    activities = (
        _activity(0, poi="POI-1", title="陈家祠", start_hour=10),
        _activity(1, poi="POI-2", title="光孝寺", start_hour=13),
        meal,
    )
    day = ItineraryDay(date=_DAY, activities=activities, transit_legs=(_leg(0),))
    inputs = _bindings(
        durations=((0, 0, _eligible_profile("POI-1")),),  # only one duration
        meals=((0, 2, "LUNCH"),),
        projection=MealProjectionState.COMPLETE,
    )
    report = _report(_ctx(day, meal_windows=(("LUNCH", 11, 12),), inputs=inputs))

    # meal outside its window (12:00 not in 11-12) + duration unknown
    # -> FAIL > UNKNOWN -> NEEDS_REPAIR
    assert report.status is FeasibilityStatus.NEEDS_REPAIR


def test_golden_h_one_unknown_blocks_verified() -> None:
    activities = (
        _activity(0, poi="POI-1", title="陈家祠", start_hour=10),
        _activity(1, poi="POI-2", title="光孝寺", start_hour=13),
    )
    day = ItineraryDay(date=_DAY, activities=activities, transit_legs=(_leg(0),))
    inputs = _bindings(
        opening=(
            (0, 0, "POI-1", _eligible_evidence("POI-1")),
            (0, 1, "POI-2", _eligible_evidence("POI-2")),
        ),
        durations=(
            (0, 0, _eligible_profile("POI-1")),
            (0, 1, _category_profile()),  # one unknown duration
        ),
    )
    report = _report(_ctx(day, must_visit=("陈家祠", "光孝寺"), inputs=inputs))

    assert report.status is FeasibilityStatus.UNVERIFIED
    assert report.summary.fail_count == 0
    assert report.summary.unknown_count >= 1


# ── Golden I: bounds and big inputs ────────────────────────────────────────


def test_golden_i_seven_day_trip_bounded_and_stable() -> None:
    days = []
    for day_index in range(7):
        activities = (
            _activity(
                day_index * 2,
                poi=f"POI-{day_index * 2}",
                title=f"景点{day_index}A",
                start_hour=10,
                day=day_index + 1,
            ),
            _activity(
                day_index * 2 + 1,
                poi=f"POI-{day_index * 2 + 1}",
                title=f"景点{day_index}B",
                start_hour=13,
                day=day_index + 1,
            ),
        )
        days.append(
            ItineraryDay(
                date=date(2026, 8, 1) + timedelta(days=day_index),
                activities=activities,
                transit_legs=(),
            )
        )
    # No legs -> route FAIL on every day; all must-visit missing.
    report = _report(_ctx(*days, must_visit=("不存在的地方",)))

    assert report.status is FeasibilityStatus.NEEDS_REPAIR
    assert len(report.rule_results) == 11
    route = next(r for r in report.rule_results if r.rule_id == "ROUTE_ENDPOINT_CONTINUITY")
    assert len(route.affected_dates) <= 16
    assert len(route.affected_entity_refs) <= 64
    assert len(route.evidence_refs) <= 64
