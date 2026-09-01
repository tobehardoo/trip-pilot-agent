"""B13_FIX R3 (P0-3) — meal activities carry an explicit meal type and the
projection binds windows to activities by type identity, never by position.

RED scenarios:
- arrival day emits only DINNER; with LUNCH+DINNER windows the dinner must
  be bound as DINNER (never LUNCH);
- lunch-only / dinner-only / both-meals days bind by type;
- disabled windows never steal a binding;
- cross-midnight placements are UNKNOWN, not a crash;
- untyped (Java-sourced) meal activities fail closed to UNKNOWN, never FAIL;
- duplicate same-type activities on one day fail closed (projection error).
"""

from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

import pytest

from trip_agent.domain.shared import CHINA_TIME_ZONE
from trip_agent.feasibility.context import ValidationContext, build_budget_context
from trip_agent.feasibility.inputs import (
    ActivityLocator,
    MealPlacementBinding,
    MealProjectionState,
    MealWindowType,
    ValidationInputs,
)
from trip_agent.feasibility.models import RuleOutcome
from trip_agent.feasibility.rules.meal import assess_meal_window
from trip_agent.infrastructure.amap.feasibility_projection import (
    project_amap_validation_inputs,
)
from trip_agent.planning.daily_schedule import DayPlan, MealDemand
from trip_agent.planning.validation_projection import project_validation_state
from trip_agent.worker.contracts import Itinerary, ItineraryActivity, ItineraryDay, MealWindow


def _activity(
    *,
    title: str,
    start: str,
    end: str,
    kind: str | None = None,
    source: str = "AMAP",
    meal_type: str | None = None,
) -> dict[str, object]:
    return {
        "activityId": None,
        "title": title,
        "startTime": start,
        "endTime": end,
        "estimatedCost": 0,
        "source": source,
        "providerPoiId": "poi-meal" if source == "AMAP" else None,
        "coordinates": (
            {"longitude": 113.26, "latitude": 23.13} if source == "AMAP" else None
        ),
        "address": "meal street" if source == "AMAP" else None,
        "kind": kind,
        "timeFixed": False,
        "locked": False,
        "typeCode": "050000" if source == "AMAP" else None,
        "typeName": "餐饮服务" if source == "AMAP" else None,
        "mealType": meal_type,
    }


def _itinerary(days: list[dict[str, object]]) -> Itinerary:
    return Itinerary.model_validate(
        {
            "title": "route",
            "days": days,
            "estimatedTotalCost": 0,
        }
    )


def _meal_day(*activities: dict[str, object], day_type: str = "ARRIVAL_DAY") -> dict[str, object]:
    return {
        "date": "2026-08-01",
        "dayType": day_type,
        "activities": list(activities),
        "transitLegs": [],
    }


def _windows(*types: str) -> tuple[MealWindow, ...]:
    defaults = {"LUNCH": ("12:00", "13:00"), "DINNER": ("18:00", "19:00")}
    return tuple(
        MealWindow.model_validate(
            {
                "mealType": meal_type,
                "startTime": defaults[meal_type][0],
                "endTime": defaults[meal_type][1],
            }
        )
        for meal_type in types
    )


# ── R3.1: meal-type identity binding in the shared projection ──────────────


def test_arrival_day_dinner_only_binds_as_dinner_not_lunch() -> None:
    """The exact P0-3 repro: with LUNCH+DINNER windows and only a dinner
    activity on the arrival day, the dinner must be bound as DINNER."""
    itinerary = _itinerary(
        [
            _meal_day(
                _activity(
                    title="晚餐",
                    start="2026-08-01T10:00:00Z",
                    end="2026-08-01T11:00:00Z",
                    kind="MEAL",
                    source="DEMO",
                    meal_type="DINNER",
                )
            )
        ]
    )
    _, inputs = project_validation_state(
        itinerary,
        requested_accommodation_label=None,
        meal_windows=_windows("LUNCH", "DINNER"),
    )
    bindings = inputs.meal_placement_bindings
    assert [b.meal_type.value for b in bindings] == ["DINNER"]
    assert bindings[0].activity == ActivityLocator(0, 0)


def test_dinner_only_day_with_only_dinner_window_binds() -> None:
    itinerary = _itinerary(
        [
            _meal_day(
                _activity(
                    title="晚餐",
                    start="2026-08-01T10:00:00Z",
                    end="2026-08-01T11:00:00Z",
                    kind="MEAL",
                    source="DEMO",
                    meal_type="DINNER",
                )
            )
        ]
    )
    _, inputs = project_validation_state(
        itinerary,
        requested_accommodation_label=None,
        meal_windows=_windows("DINNER"),
    )
    assert [b.meal_type.value for b in inputs.meal_placement_bindings] == ["DINNER"]


def test_lunch_only_day_binds_lunch() -> None:
    itinerary = _itinerary(
        [
            _meal_day(
                _activity(
                    title="午餐",
                    start="2026-08-01T04:00:00Z",
                    end="2026-08-01T05:00:00Z",
                    kind="MEAL",
                    source="DEMO",
                    meal_type="LUNCH",
                ),
                day_type="FULL_DAY",
            )
        ]
    )
    _, inputs = project_validation_state(
        itinerary,
        requested_accommodation_label=None,
        meal_windows=_windows("LUNCH"),
    )
    assert [b.meal_type.value for b in inputs.meal_placement_bindings] == ["LUNCH"]


def test_both_meals_bind_by_type_in_any_activity_order() -> None:
    """Dinner declared before lunch in the itinerary still binds by type."""
    itinerary = _itinerary(
        [
            _meal_day(
                _activity(
                    title="晚餐",
                    start="2026-08-01T10:00:00Z",
                    end="2026-08-01T11:00:00Z",
                    kind="MEAL",
                    source="DEMO",
                    meal_type="DINNER",
                ),
                _activity(
                    title="午餐",
                    start="2026-08-01T04:00:00Z",
                    end="2026-08-01T05:00:00Z",
                    kind="MEAL",
                    source="DEMO",
                    meal_type="LUNCH",
                ),
                day_type="FULL_DAY",
            )
        ]
    )
    _, inputs = project_validation_state(
        itinerary,
        requested_accommodation_label=None,
        meal_windows=_windows("LUNCH", "DINNER"),
    )
    by_type = {
        b.meal_type.value: b.activity.activity_index
        for b in inputs.meal_placement_bindings
    }
    assert by_type == {"LUNCH": 1, "DINNER": 0}


def test_disabled_window_never_steals_a_binding() -> None:
    itinerary = _itinerary(
        [
            _meal_day(
                _activity(
                    title="晚餐",
                    start="2026-08-01T10:00:00Z",
                    end="2026-08-01T11:00:00Z",
                    kind="MEAL",
                    source="DEMO",
                    meal_type="DINNER",
                )
            )
        ]
    )
    _, inputs = project_validation_state(
        itinerary,
        requested_accommodation_label=None,
        meal_windows=(
            MealWindow.model_validate(
                {
                    "mealType": "DINNER",
                    "startTime": "18:00",
                    "endTime": "19:00",
                    "source": "DISABLED",
                }
            ),
            MealWindow.model_validate(
                {"mealType": "LUNCH", "startTime": "12:00", "endTime": "13:00"}
            ),
        ),
    )
    assert [b.meal_type.value for b in inputs.meal_placement_bindings] == []


# ── R3.2: untyped meal activities fail closed to UNKNOWN ───────────────────


def test_untyped_meal_activities_are_never_positionally_bound() -> None:
    """Java-sourced replan/candidate itineraries carry no meal type; the
    projection must not guess by position (the exact old zip behavior)."""
    itinerary = _itinerary(
        [
            _meal_day(
                _activity(
                    title="晚餐",
                    start="2026-08-01T10:00:00Z",
                    end="2026-08-01T11:00:00Z",
                    kind="MEAL",
                    source="DEMO",
                )
            )
        ]
    )
    _, inputs = project_validation_state(
        itinerary,
        requested_accommodation_label=None,
        meal_windows=_windows("DINNER"),
    )
    assert inputs.meal_placement_bindings == ()
    assert 0 in inputs.unverified_meal_days


def test_rule_reports_unverified_day_as_unknown_not_missing() -> None:
    ctx = _rule_context(
        itinerary=_itinerary(
            [
                _meal_day(
                    _activity(
                        title="晚餐",
                        start="2026-08-01T10:00:00Z",
                        end="2026-08-01T11:00:00Z",
                        kind="MEAL",
                        source="DEMO",
                    )
                )
            ]
        ),
        windows=_windows("DINNER"),
        inputs=ValidationInputs(
            meal_placement_bindings=(),
            meal_projection_state=MealProjectionState.COMPLETE,
            unverified_meal_days=(0,),
        ),
    )
    assessment = assess_meal_window(ctx)
    assert assessment.result.outcome is RuleOutcome.UNKNOWN
    assert assessment.result.reason_code == "MEAL_WINDOW_UNVERIFIED"


# ── R3.3: duplicates fail closed ───────────────────────────────────────────


def test_duplicate_same_type_on_one_day_fails_closed() -> None:
    itinerary = _itinerary(
        [
            _meal_day(
                _activity(
                    title="晚餐",
                    start="2026-08-01T10:00:00Z",
                    end="2026-08-01T11:00:00Z",
                    kind="MEAL",
                    source="DEMO",
                    meal_type="DINNER",
                ),
                _activity(
                    title="晚餐2",
                    start="2026-08-01T12:00:00Z",
                    end="2026-08-01T13:00:00Z",
                    kind="MEAL",
                    source="DEMO",
                    meal_type="DINNER",
                ),
            )
        ]
    )
    with pytest.raises(ValueError):
        project_validation_state(
            itinerary,
            requested_accommodation_label=None,
            meal_windows=_windows("DINNER"),
        )


# ── R3.4: AMap projection binds by type identity too ───────────────────────


def test_amap_projection_binds_by_meal_type_identity() -> None:
    day_plan = DayPlan(
        date=date(2026, 8, 1),
        day_type="FULL_DAY",
        window_start_minute=540,
        window_end_minute=1080,
        items=(),
        meal_demands=(
            MealDemand(meal_type="DINNER", start_minute=1080, end_minute=1140),
            MealDemand(meal_type="LUNCH", start_minute=720, end_minute=780),
        ),
        origin=None,
        accommodation_unknown=False,
        warnings=(),
    )
    itinerary = _itinerary(
        [
            {
                "date": "2026-08-01",
                "dayType": "FULL_DAY",
                "activities": [
                    _activity(
                        title="晚餐",
                        start="2026-08-01T10:00:00Z",
                        end="2026-08-01T11:00:00Z",
                        kind="MEAL",
                        source="AMAP",
                        meal_type="DINNER",
                    ),
                    _activity(
                        title="午餐",
                        start="2026-08-01T04:00:00Z",
                        end="2026-08-01T05:00:00Z",
                        kind="MEAL",
                        source="AMAP",
                        meal_type="LUNCH",
                    ),
                ],
                "transitLegs": [],
            }
        ]
    )
    inputs = project_amap_validation_inputs(
        itinerary=itinerary,
        day_plans=(day_plan,),
        fetched_snapshots=(),
    )
    by_type = {
        b.meal_type.value: b.activity.activity_index
        for b in inputs.meal_placement_bindings
    }
    assert by_type == {"LUNCH": 1, "DINNER": 0}


# ── R3.5: cross-midnight placement is UNKNOWN, never a crash ───────────────


def test_cross_midnight_placement_is_unknown_not_crash() -> None:
    start = datetime(2026, 8, 1, 23, 0, tzinfo=CHINA_TIME_ZONE)
    end = datetime(2026, 8, 2, 0, 30, tzinfo=CHINA_TIME_ZONE)
    activity = ItineraryActivity(
        activity_id=UUID(int=1),
        title="跨午夜晚餐",
        start_time=start,
        end_time=end,
        estimated_cost=Decimal("0"),
        source="DEMO",
        kind="MEAL",
        meal_type="DINNER",
    )
    itinerary = Itinerary(
        title="route",
        days=(ItineraryDay(date=date(2026, 8, 1), activities=(activity,), transit_legs=()),),
        estimated_total_cost=Decimal("0"),
    )
    ctx = _rule_context(
        itinerary=itinerary,
        windows=_windows("DINNER"),
        inputs=ValidationInputs(
            meal_placement_bindings=(
                MealPlacementBinding(
                    activity=ActivityLocator(0, 0),
                    meal_type=MealWindowType.DINNER,
                ),
            ),
            meal_projection_state=MealProjectionState.COMPLETE,
        ),
    )
    assessment = assess_meal_window(ctx)
    assert assessment.result.outcome is RuleOutcome.UNKNOWN
    assert assessment.result.reason_code == "MEAL_WINDOW_UNVERIFIED"


# ── helpers ────────────────────────────────────────────────────────────────


def _rule_context(
    *,
    itinerary: Itinerary,
    windows: tuple[MealWindow, ...],
    inputs: ValidationInputs,
) -> ValidationContext:
    command = _dummy_command(windows=windows)
    return ValidationContext(
        command=command,
        itinerary=itinerary,
        budget=build_budget_context(command, itinerary),
        validation_inputs=inputs,
    )


def _dummy_command(windows: tuple[MealWindow, ...]):
    from trip_agent.worker.contracts import PlanningCreateCommand

    payload = deepcopy(
        {
            "eventType": "PLANNING_CREATE_REQUESTED",
            "schemaVersion": 4,
            "eventId": "11111111-1111-4111-8111-111111111111",
            "traceId": "22222222-2222-4222-8222-222222222222",
            "taskId": "33333333-3333-4333-8333-333333333333",
            "tripId": "44444444-4444-4444-8444-444444444444",
            "occurredAt": "2026-07-31T02:00:00Z",
            "payload": {
                "taskType": "CREATE",
                "baselineTripVersion": 0,
                "idempotencyKey": "55555555-5555-4555-8555-555555555555",
                "trip": {
                    "title": "meal",
                    "destination": "广州",
                    "startDate": "2026-08-01",
                    "endDate": "2026-08-01",
                    "status": "DRAFT",
                    "version": 0,
                    "arrivalAt": "2026-08-01T08:00:00+08:00",
                    "departureAt": "2026-08-01T20:00:00+08:00",
                    "constraints": {
                        "budgetAmount": 1000,
                        "travelers": 1,
                        "travelerType": "SOLO",
                        "pace": "BALANCED",
                        "preferences": [],
                        "fixedSchedules": [],
                        "arrival": None,
                        "departure": None,
                        "accommodation": None,
                        "mustVisitPlaces": [],
                        "avoidPlaces": [],
                        "mustVisitPlaceRefs": [],
                        "avoidPlaceRefs": [],
                        "mealWindows": [
                            {
                                "mealType": w.meal_type,
                                "startTime": w.start_time,
                                "endTime": w.end_time,
                            }
                            for w in windows
                        ],
                        "mobilityLevel": "STANDARD",
                        "schemaVersion": 3,
                    },
                },
                "guideEvidence": {"facts": []},
                "planningContext": {
                    "snapshotId": "66666666-6666-4666-8666-666666666666",
                    "schemaVersion": 3,
                    "tripId": "44444444-4444-4444-8444-444444444444",
                    "planningTaskId": "33333333-3333-4333-8333-333333333333",
                    "city": "广州",
                    "travelStartDate": "2026-08-01",
                    "travelEndDate": "2026-08-01",
                    "generatedAt": "2026-07-31T02:00:00Z",
                    "stale": False,
                    "sources": [],
                    "facts": [],
                    "conflicts": [],
                    "excludedFacts": [],
                    "diagnostics": [],
                },
            },
        }
    )
    return PlanningCreateCommand.model_validate(payload)
