"""B5 Phase 8 — AMap transient validation-inputs projection (pure adapter)."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest

from trip_agent.domain.shared import CHINA_TIME_ZONE
from trip_agent.feasibility.inputs import MealProjectionState, ValidationInputs
from trip_agent.infrastructure.amap.feasibility_projection import (
    project_amap_validation_inputs,
)
from trip_agent.planning.daily_schedule import DayPlan, MealDemand
from trip_agent.providers.map import Coordinates, Poi
from trip_agent.worker.contracts import (
    ActivityCoordinates,
    Itinerary,
    ItineraryActivity,
    ItineraryDay,
)


def _poi(provider_id: str, *, hours: str = "09:00-18:00") -> Poi:
    return Poi(
        provider_id=provider_id,
        name=f"POI {provider_id}",
        coordinates=Coordinates(longitude=113.31, latitude=23.13),
        type_name="风景名胜",
        type_code="110000",
        province="广东省",
        city="广州市",
        district="越秀区",
        address="addr",
        business_hours_today=hours,
    )


class _Snapshot:
    def __init__(self, poi: Poi, fetched_at: datetime) -> None:
        self.poi = poi
        self.fetched_at = fetched_at


def _activity(
    index: int,
    *,
    poi: str,
    kind: str = "ATTRACTION",
    start_hour: int = 10,
) -> ItineraryActivity:
    start = datetime(2026, 8, 1, start_hour, tzinfo=CHINA_TIME_ZONE)
    return ItineraryActivity(
        activity_id=UUID(int=index + 1),
        title=f"Activity {index}",
        start_time=start,
        end_time=start + timedelta(minutes=60),
        estimated_cost=Decimal("0"),
        source="AMAP",
        provider_poi_id=poi,
        coordinates=ActivityCoordinates(longitude=Decimal("113.31"), latitude=Decimal("23.13")),
        address="addr",
        kind=kind,  # type: ignore[arg-type]
    )


def _meal_activity(index: int, *, start_hour: int = 12) -> ItineraryActivity:
    start = datetime(2026, 8, 1, start_hour, tzinfo=CHINA_TIME_ZONE)
    return ItineraryActivity(
        activity_id=UUID(int=index + 1),
        title="meal",
        start_time=start,
        end_time=start + timedelta(minutes=60),
        estimated_cost=Decimal("0"),
        source="AMAP",
        provider_poi_id="REST-1",
        coordinates=ActivityCoordinates(longitude=Decimal("113.31"), latitude=Decimal("23.13")),
        address="addr",
        kind="MEAL",
    )


def _day_plan(*demands: tuple[str, int, int]) -> DayPlan:
    return DayPlan(
        date=date(2026, 8, 1),
        day_type="FULL_DAY",
        window_start_minute=540,
        window_end_minute=1080,
        items=(),
        meal_demands=tuple(
            MealDemand(meal_type=meal_type, start_minute=start, end_minute=end)  # type: ignore[arg-type]
            for meal_type, start, end in demands
        ),
        origin=None,
        accommodation_unknown=False,
        warnings=(),
    )


def _itinerary(*activities: ItineraryActivity) -> Itinerary:
    return Itinerary(
        title="amap",
        days=(ItineraryDay(date=date(2026, 8, 1), activities=activities, transit_legs=()),),
        estimated_total_cost=Decimal("0"),
    )


def test_projection_builds_opening_bindings_for_matching_pois() -> None:
    poi_a = _poi("POI-1")
    poi_b = _poi("POI-2")
    inputs = project_amap_validation_inputs(
        itinerary=_itinerary(
            _activity(0, poi="POI-1"),
            _activity(1, poi="POI-2"),
        ),
        day_plans=(_day_plan(),),
        fetched_snapshots=(
            _Snapshot(poi_a, datetime(2026, 8, 1, 8, 0, tzinfo=UTC)),
            _Snapshot(poi_b, datetime(2026, 8, 1, 9, 0, tzinfo=UTC)),
        ),
    )

    assert len(inputs.opening_hours_bindings) == 2
    assert all(binding.poi_key in {"POI-1", "POI-2"} for binding in inputs.opening_hours_bindings)


def test_fetched_at_is_per_poi_batch() -> None:
    poi_a = _poi("POI-1")
    poi_b = _poi("POI-2")
    inputs = project_amap_validation_inputs(
        itinerary=_itinerary(_activity(0, poi="POI-1"), _activity(1, poi="POI-2")),
        day_plans=(_day_plan(),),
        fetched_snapshots=(
            _Snapshot(poi_a, datetime(2026, 8, 1, 8, 0, tzinfo=UTC)),
            _Snapshot(poi_b, datetime(2026, 8, 1, 9, 0, tzinfo=UTC)),
        ),
    )

    binding_a = next(b for b in inputs.opening_hours_bindings if b.poi_key == "POI-1")
    binding_b = next(b for b in inputs.opening_hours_bindings if b.poi_key == "POI-2")
    assert binding_a.evidences[0].checked_at == datetime(2026, 8, 1, 8, 0, tzinfo=UTC)
    assert binding_b.evidences[0].checked_at == datetime(2026, 8, 1, 9, 0, tzinfo=UTC)


def test_amap_evidence_is_never_hard_eligible() -> None:
    poi = _poi("POI-1")
    inputs = project_amap_validation_inputs(
        itinerary=_itinerary(_activity(0, poi="POI-1")),
        day_plans=(_day_plan(),),
        fetched_snapshots=(_Snapshot(poi, datetime(2026, 8, 1, 8, 0, tzinfo=UTC)),),
    )

    for binding in inputs.opening_hours_bindings:
        for evidence in binding.evidences:
            assert evidence.hard_constraint_eligible is False


def test_duration_bindings_use_category_profile() -> None:
    poi = _poi("POI-1")
    inputs = project_amap_validation_inputs(
        itinerary=_itinerary(_activity(0, poi="POI-1")),
        day_plans=(_day_plan(),),
        fetched_snapshots=(_Snapshot(poi, datetime(2026, 8, 1, 8, 0, tzinfo=UTC)),),
    )

    assert len(inputs.visit_duration_bindings) == 1
    profile = inputs.visit_duration_bindings[0].profile
    assert profile.hard_constraint_eligible is False


def test_meal_bindings_follow_day_plan_demands_in_order() -> None:
    poi = _poi("POI-1")
    inputs = project_amap_validation_inputs(
        itinerary=_itinerary(
            _activity(0, poi="POI-1"),
            _meal_activity(1),
        ),
        day_plans=(_day_plan(("LUNCH", 720, 780)),),
        fetched_snapshots=(_Snapshot(poi, datetime(2026, 8, 1, 8, 0, tzinfo=UTC)),),
    )

    assert len(inputs.meal_placement_bindings) == 1
    binding = inputs.meal_placement_bindings[0]
    assert binding.meal_type.value == "LUNCH"
    assert binding.activity.day_index == 0
    assert binding.activity.activity_index == 1
    assert inputs.meal_projection_state is MealProjectionState.COMPLETE


def test_meal_count_mismatch_raises_value_error() -> None:
    poi = _poi("POI-1")
    with pytest.raises(ValueError):
        project_amap_validation_inputs(
            itinerary=_itinerary(_activity(0, poi="POI-1")),
            day_plans=(_day_plan(("LUNCH", 720, 780)),),
            fetched_snapshots=(_Snapshot(poi, datetime(2026, 8, 1, 8, 0, tzinfo=UTC)),),
        )


def test_unmatched_poi_gets_no_bindings() -> None:
    poi = _poi("POI-1")
    inputs = project_amap_validation_inputs(
        itinerary=_itinerary(_activity(0, poi="OTHER-POI")),
        day_plans=(_day_plan(),),
        fetched_snapshots=(_Snapshot(poi, datetime(2026, 8, 1, 8, 0, tzinfo=UTC)),),
    )

    assert inputs.opening_hours_bindings == ()
    assert inputs.visit_duration_bindings == ()


def test_projection_is_pure_and_returns_immutable_inputs() -> None:
    poi = _poi("POI-1")
    inputs = project_amap_validation_inputs(
        itinerary=_itinerary(_activity(0, poi="POI-1")),
        day_plans=(_day_plan(),),
        fetched_snapshots=(_Snapshot(poi, datetime(2026, 8, 1, 8, 0, tzinfo=UTC)),),
    )
    assert isinstance(inputs, ValidationInputs)
    assert isinstance(inputs.opening_hours_bindings, tuple)
