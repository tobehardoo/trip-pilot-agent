"""Tests for the daily-skeleton producer path (the production planning path)."""

import asyncio
from copy import deepcopy
from datetime import UTC, date, datetime, time
from decimal import Decimal
from uuid import UUID

import pytest
from test_planning_worker import COMMAND

from trip_agent.domain.planning.protocols import (
    PlanningInfeasibleError,
    PlanningResult,
)
from trip_agent.domain.shared import CHINA_TIME_ZONE
from trip_agent.infrastructure.amap.planning_provider import AmapPlanningProvider
from trip_agent.planning.trip_skeleton import (
    AccommodationState,
    AreaEstimatedAccommodation,
    ConfirmedAccommodation,
    UnresolvedAccommodation,
)
from trip_agent.providers.map import (
    Coordinates,
    Poi,
    ProviderSuccess,
)
from trip_agent.providers.route import RoutePlan, RouteStep
from trip_agent.worker.contracts import (
    Itinerary,
    ItineraryActivity,
    ItineraryDay,
    PlanningCreateCommand,
)


def _minimal_itinerary() -> Itinerary:
    activity = ItineraryActivity(
        activity_id=UUID("3d76fb9e-362e-4b28-8a9e-18e8ac7050ad"),
        title="t",
        start_time=datetime(2026, 8, 1, 9, 0, tzinfo=UTC),
        end_time=datetime(2026, 8, 1, 10, 0, tzinfo=UTC),
        estimated_cost=Decimal("0"),
        source="DEMO",
    )
    return Itinerary(
        title="t",
        days=(
            ItineraryDay(
                date=date(2026, 8, 1),
                activities=(activity,),
                transit_legs=(),
            ),
        ),
        estimated_total_cost=Decimal("0"),
    )


def _poi(
    provider_id: str,
    name: str,
    *,
    district: str = "越秀区",
    type_code: str = "110000",
    type_name: str = "风景名胜",
) -> Poi:
    return Poi(
        provider_id=provider_id,
        name=name,
        coordinates=Coordinates(longitude=113.31, latitude=23.13),
        type_name=type_name,
        type_code=type_code,
        province="广东省",
        city="广州市",
        district=district,
        address=f"{name}地址",
    )


class StaticMapProvider:
    def __init__(
        self,
        pois: tuple[Poi, ...],
        *,
        meal_pois: tuple[Poi, ...] = (),
        accommodation_poi: Poi | None = None,
    ) -> None:
        self._pois = pois
        self._meal_pois = meal_pois
        self._accommodation_poi = accommodation_poi

    async def search_pois(self, request: object):
        keyword = request.keyword
        if keyword in {"广州站", "广州南站"}:
            return self._success((_poi("anchor-station", keyword),))
        if self._accommodation_poi is not None and keyword == "广州花园酒店":
            return self._success((self._accommodation_poi,))
        if keyword == "美食" or keyword.endswith(" 美食"):
            return self._success(self._meal_pois)
        return self._success(self._pois)

    @staticmethod
    def _success(pois: tuple[Poi, ...]) -> ProviderSuccess[tuple[Poi, ...]]:
        return ProviderSuccess(
            data=pois,
            provider="AMAP",
            latency_ms=1,
            cached=False,
            fetched_at=datetime(2026, 7, 23, tzinfo=UTC),
            estimated=False,
        )


class SuccessfulRouteProvider:
    """Fake AMAP route provider so legs are AMAP and provenance stays valid."""

    def __init__(self, duration_seconds: int = 900) -> None:
        self._duration_seconds = duration_seconds

    async def get_route(self, request: object):
        return ProviderSuccess(
            data=RoutePlan(
                mode="WALKING",
                distance_meters=1200,
                duration_seconds=self._duration_seconds,
                steps=(
                    RouteStep(
                        instruction="Walk",
                        distance_meters=1200,
                        duration_seconds=self._duration_seconds,
                        polyline=(request.origin, request.destination),
                    ),
                ),
                polyline=(request.origin, request.destination),
            ),
            provider="AMAP",
            latency_ms=1,
            cached=False,
            fetched_at=datetime(2026, 7, 23, tzinfo=UTC),
            estimated=False,
        )


class FirstRouteDelayProvider(SuccessfulRouteProvider):
    """Only the first route is long, reproducing a delayed activity before a
    later fixed departure whose own incoming route still fits."""

    def __init__(self) -> None:
        super().__init__(duration_seconds=60)
        self._call_count = 0

    async def get_route(self, request: object):
        self._call_count += 1
        self._duration_seconds = 60 * 60 if self._call_count == 1 else 60
        return await super().get_route(request)


def _command(
    *,
    start: str = "2026-08-01",
    end: str = "2026-08-03",
    arrival: dict | None = None,
    departure: dict | None = None,
    accommodation: dict | None = None,
    must_visit: list[str] | None = None,
    preferences: list[str] | None = None,
    pace: str = "BALANCED",
    fixed_schedules: list[dict] | None = None,
    arrival_at: str | None = None,
    departure_at: str | None = None,
) -> PlanningCreateCommand:
    payload = deepcopy(COMMAND)
    payload["schemaVersion"] = 2
    payload["payload"]["trip"]["startDate"] = start
    payload["payload"]["trip"]["endDate"] = end
    constraints = payload["payload"]["trip"]["constraints"]
    constraints["schemaVersion"] = 2
    constraints["preferences"] = preferences or ["美食", "历史"]
    constraints["pace"] = pace
    constraints["arrival"] = arrival
    constraints["departure"] = departure
    constraints["accommodation"] = accommodation
    constraints["mustVisitPlaces"] = must_visit or []
    constraints["avoidPlaces"] = []
    constraints["mealWindows"] = []
    constraints["mobilityLevel"] = "STANDARD"
    constraints["fixedSchedules"] = fixed_schedules or []
    if arrival_at is not None or departure_at is not None:
        # B13_FIX R1: authoritative snapshot boundaries (create v4 shape).
        payload["schemaVersion"] = 4
        constraints["schemaVersion"] = 3
        constraints.pop("arrival", None)
        constraints.pop("departure", None)
        trip = payload["payload"]["trip"]
        trip["arrivalAt"] = arrival_at
        trip["departureAt"] = departure_at
        trip["arrivalAt"] = arrival_at
        trip["departureAt"] = departure_at
        payload["payload"]["planningContext"] = {
            "snapshotId": "67396263-bac9-4db8-bc4c-08d57493ba26",
            "schemaVersion": 3,
            "tripId": payload["tripId"],
            "planningTaskId": payload["taskId"],
            "city": trip["destination"],
            "travelStartDate": trip["startDate"],
            "travelEndDate": trip["endDate"],
            "generatedAt": "2026-07-13T08:00:00Z",
            "stale": False,
            "sources": [],
            "facts": [],
            "conflicts": [],
            "excludedFacts": [],
            "diagnostics": [],
        }
    return PlanningCreateCommand.model_validate(payload)


def _provider(
    pois: tuple[Poi, ...],
    *,
    meal_pois: tuple[Poi, ...] = (),
    accommodation_poi: Poi | None = None,
) -> AmapPlanningProvider:
    return AmapPlanningProvider(
        StaticMapProvider(pois, meal_pois=meal_pois, accommodation_poi=accommodation_poi),
        SuccessfulRouteProvider(),
    )


# ── skeleton behavior --------------------------------------------------------


def test_skeleton_emits_arrival_day_type_and_anchor_kind() -> None:
    pois = (_poi("p1", "越秀公园"), _poi("p2", "陈家祠"), _poi("p3", "广州塔"))
    result = asyncio.run(
        _provider(pois).plan(
            _command(arrival={"placeName": "广州站", "time": "2026-08-01T14:00:00+08:00"})
        )
    )

    first_day = result.itinerary.days[0]
    assert first_day.day_type == "ARRIVAL_DAY"
    arrival_activity = next(a for a in first_day.activities if a.kind == "ARRIVAL")
    assert arrival_activity.time_fixed is True
    assert arrival_activity.provider_poi_id == "anchor-station"
    assert result.itinerary.days[1].day_type == "FULL_DAY"


def test_skeleton_marks_departure_anchor() -> None:
    pois = (_poi("p1", "越秀公园"), _poi("p2", "陈家祠"), _poi("p3", "广州塔"))
    result = asyncio.run(
        _provider(pois).plan(
            _command(departure={"placeName": "广州南站", "time": "2026-08-03T11:00:00+08:00"})
        )
    )

    last_day = result.itinerary.days[-1]
    assert last_day.day_type == "DEPARTURE_DAY"
    departure_activity = next(a for a in last_day.activities if a.kind == "DEPARTURE")
    assert departure_activity.time_fixed is True


def test_skeleton_emits_unresolved_meal_without_fake_poi() -> None:
    # meal_pois empty => restaurant resolution fails => MEAL node without POI.
    pois = (_poi("p1", "越秀公园"), _poi("p2", "陈家祠"), _poi("p3", "广州塔"))
    result = asyncio.run(_provider(pois).plan(_command()))

    meal_activities = tuple(
        a for day in result.itinerary.days for a in day.activities if a.kind == "MEAL"
    )
    assert meal_activities, "a full day must reserve meal time"
    for activity in meal_activities:
        assert activity.provider_poi_id is None
        assert activity.coordinates is None
        assert "建议在当前区域自行选择餐馆" in activity.title


def test_skeleton_uses_each_restaurant_at_most_once_when_alternatives_exist() -> None:
    first_meal = _poi(
        "r1", "老字号粤菜馆", district="越秀区", type_code="050000", type_name="餐饮服务"
    )
    second_meal = _poi(
        "r2", "西关粤菜馆", district="越秀区", type_code="050000", type_name="餐饮服务"
    )
    pois = (_poi("p1", "越秀公园"), _poi("p2", "陈家祠"), _poi("p3", "广州塔"))
    result = asyncio.run(_provider(pois, meal_pois=(first_meal, second_meal)).plan(_command()))

    meal_activities = tuple(
        a for day in result.itinerary.days for a in day.activities if a.kind == "MEAL"
    )
    assert meal_activities
    resolved_ids = tuple(
        activity.provider_poi_id
        for activity in meal_activities
        if activity.provider_poi_id is not None
    )
    assert resolved_ids == ("r1", "r2")
    assert len(resolved_ids) == len(set(resolved_ids))
    assert any(activity.provider_poi_id is None for activity in meal_activities)


def test_skeleton_full_day_experience_becomes_special_day() -> None:
    mountain = _poi("exp-1", "长隆欢乐世界", district="番禺区")
    pois = (mountain, _poi("p1", "越秀公园"), _poi("p2", "陈家祠"))
    result = asyncio.run(_provider(pois).plan(_command()))

    special_days = [day for day in result.itinerary.days if day.day_type == "SPECIAL_ACTIVITY_DAY"]
    assert special_days
    experience = next(a for a in special_days[0].activities if a.kind == "EXPERIENCE")
    assert experience.title == "长隆欢乐世界"


def test_skeleton_emits_unresolved_accommodation_without_fake_hotel() -> None:
    pois = (_poi("p1", "越秀公园"), _poi("p2", "陈家祠"), _poi("p3", "广州塔"))
    result = asyncio.run(_provider(pois).plan(_command()))

    accommodation_nodes = tuple(
        a for day in result.itinerary.days for a in day.activities if a.kind == "ACCOMMODATION"
    )
    assert accommodation_nodes, "multi-day plans must preserve accommodation semantics"
    assert all(a.provider_poi_id is None for a in accommodation_nodes)
    assert all(a.coordinates is None for a in accommodation_nodes)
    assert all("住宿地点待确认" in a.title for a in accommodation_nodes)


def test_skeleton_does_not_repeat_attractions_across_days() -> None:
    pois = tuple(_poi(f"p{index}", f"景点{index}") for index in range(1, 8))

    result = asyncio.run(_provider(pois).plan(_command()))

    placed_ids = [
        activity.provider_poi_id
        for day in result.itinerary.days
        for activity in day.activities
        if activity.kind in {"ATTRACTION", "EXPERIENCE"}
    ]
    assert len(placed_ids) == len(set(placed_ids))


def test_small_scenic_poi_uses_normal_not_half_day_duration() -> None:
    scenic_poi = _poi("small-scenic", "社区小公园")

    assert AmapPlanningProvider._magnitude_for_poi(scenic_poi) == "NORMAL"


def test_skeleton_emits_hotel_nodes_when_accommodation_known() -> None:
    hotel = _poi(
        "hotel-1", "广州花园酒店", district="越秀区", type_code="100000", type_name="住宿服务"
    )
    pois = (_poi("p1", "越秀公园"), _poi("p2", "陈家祠"))
    result = asyncio.run(
        _provider(pois, accommodation_poi=hotel).plan(
            _command(accommodation={"placeName": "广州花园酒店"})
        )
    )

    accommodation_nodes = tuple(
        a for day in result.itinerary.days for a in day.activities if a.kind == "ACCOMMODATION"
    )
    assert accommodation_nodes, "known accommodation must appear as start/end nodes"
    assert all(a.provider_poi_id == "hotel-1" for a in accommodation_nodes)


def test_skeleton_activities_carry_kind_and_time_fixed() -> None:
    pois = (_poi("p1", "越秀公园"), _poi("p2", "陈家祠"), _poi("p3", "广州塔"))
    result = asyncio.run(_provider(pois).plan(_command()))

    for day in result.itinerary.days:
        assert day.day_type in {
            "ARRIVAL_DAY",
            "FULL_DAY",
            "DEPARTURE_DAY",
            "SPECIAL_ACTIVITY_DAY",
        }
        for activity in day.activities:
            assert activity.kind in {
                "ATTRACTION",
                "EXPERIENCE",
                "MEAL",
                "ACCOMMODATION",
                "ARRIVAL",
                "DEPARTURE",
            }
            assert activity.time_fixed in {True, False}


# ── flag decoupling ----------------------------------------------------------


def test_amap_result_serializes_as_completed_v10_valid() -> None:
    import json
    from pathlib import Path

    import jsonschema

    from trip_agent.worker.processor import process_planning_create

    pois = (_poi("p1", "越秀公园"), _poi("p2", "陈家祠"), _poi("p3", "广州塔"))
    command = _command()
    completed = asyncio.run(
        process_planning_create(
            command,
            _provider(pois),
        )
    )
    # AMap without confirmed accommodation -> UNVERIFIED report, but no
    # blocker (B16: Information Missing != Planning Failed) -> v10 completed.
    assert completed.schema_version == 11
    assert completed.event_type == "PLANNING_COMPLETED"
    assert completed.payload.has_blocker is False

    payload = completed.model_dump_json(by_alias=True, exclude_none=True)
    schema = json.loads(
        Path("../../contracts/messaging/planning-completed-event-v11.schema.json").read_text(
            encoding="utf-8"
        )
    )
    jsonschema.validate(json.loads(payload), schema)


def test_producer_no_longer_writes_v8_completion() -> None:
    from trip_agent.worker.processor import process_planning_create

    pois = (_poi("p1", "越秀公园"), _poi("p2", "陈家祠"), _poi("p3", "广州塔"))
    command = _command()
    completed = asyncio.run(process_planning_create(command, _provider(pois)))
    # Producer now writes the v10 completion (not v9, never v8).
    assert completed.schema_version == 11
    assert completed.event_type == "PLANNING_COMPLETED"
    assert completed.payload.has_blocker is False


def test_demo_skeleton_classifies_days_and_marks_anchors() -> None:
    from trip_agent.infrastructure.demo.planning_provider import DemoPlanningProvider

    provider = DemoPlanningProvider()
    result = asyncio.run(
        provider.plan(
            _command(arrival={"placeName": "广州站", "time": "2026-08-01T16:00:00+08:00"})
        )
    )
    first = result.itinerary.days[0]
    assert first.day_type == "ARRIVAL_DAY"
    assert any(a.kind == "ARRIVAL" and a.time_fixed for a in first.activities)
    assert result.itinerary.days[1].day_type == "FULL_DAY"


def test_fixed_schedule_is_mapped_from_contract_fields() -> None:
    """Regression: contracts.FixedSchedule (start_time) must map to the daily
    scheduler's FixedSchedule (start/end) instead of crashing on `.start`."""
    pois = (_poi("p1", "越秀公园"), _poi("p2", "陈家祠"), _poi("p3", "广州塔"))
    result = asyncio.run(
        _provider(pois).plan(
            _command(
                fixed_schedules=[
                    {
                        "placeName": "陈家祠",
                        "startTime": "2026-08-02T14:00:00+08:00",
                        "endTime": "2026-08-02T16:00:00+08:00",
                    }
                ]
            )
        )
    )
    day2 = result.itinerary.days[1]
    fixed = next(a for a in day2.activities if a.title == "陈家祠" and a.time_fixed)
    assert fixed.kind == "ATTRACTION"
    # Scheduled window is preserved in the source timezone (Asia/Shanghai).
    assert fixed.start_time.strftime("%H:%M") == "14:00"
    assert fixed.end_time.strftime("%H:%M") == "16:00"


def test_late_arrival_keeps_arrival_anchor_via_provider() -> None:
    """Regression: a 20:00 arrival must keep the ARRIVAL node and not drop to a
    null-window empty day."""
    pois = (_poi("p1", "越秀公园"), _poi("p2", "陈家祠"), _poi("p3", "广州塔"))
    result = asyncio.run(
        _provider(pois).plan(
            _command(arrival={"placeName": "广州站", "time": "2026-08-01T20:00:00+08:00"})
        )
    )
    day1 = result.itinerary.days[0]
    assert day1.day_type == "ARRIVAL_DAY"
    assert any(a.kind == "ARRIVAL" for a in day1.activities)


def test_early_departure_keeps_departure_anchor_via_provider() -> None:
    """Regression: a 08:00 departure must keep the DEPARTURE node."""
    pois = (_poi("p1", "越秀公园"), _poi("p2", "陈家祠"), _poi("p3", "广州塔"))
    result = asyncio.run(
        _provider(pois).plan(
            _command(departure={"placeName": "广州南站", "time": "2026-08-03T08:00:00+08:00"})
        )
    )
    day3 = result.itinerary.days[-1]
    assert day3.day_type == "DEPARTURE_DAY"
    assert any(a.kind == "DEPARTURE" for a in day3.activities)


# ── B13_FIX R1: authoritative snapshot boundary times ────────────────────────


def test_late_arrival_first_activity_not_before_snapshot_boundary() -> None:
    """P0-1: an 18:00 arrival must never place the first activity at 09:00."""
    pois = (_poi("p1", "越秀公园"), _poi("p2", "陈家祠"), _poi("p3", "广州塔"))
    result = asyncio.run(
        _provider(pois).plan(
            _command(
                start="2026-08-01",
                end="2026-08-02",
                arrival_at="2026-08-01T18:00:00+08:00",
                departure_at="2026-08-02T17:00:00+08:00",
            )
        )
    )
    first_day = result.itinerary.days[0]
    assert first_day.day_type == "ARRIVAL_DAY"
    first_activity = first_day.activities[0]
    assert first_activity.start_time.astimezone(CHINA_TIME_ZONE).time() >= time(18, 0)
    arrival_activity = next(a for a in first_day.activities if a.kind == "ARRIVAL")
    assert arrival_activity.start_time.astimezone(CHINA_TIME_ZONE).time() == time(18, 0)


def test_early_departure_last_activity_not_after_snapshot_boundary() -> None:
    """P0-1: an 08:00 departure must never leave activities after 08:00."""
    pois = (_poi("p1", "越秀公园"), _poi("p2", "陈家祠"), _poi("p3", "广州塔"))
    result = asyncio.run(
        _provider(pois).plan(
            _command(
                start="2026-08-01",
                end="2026-08-02",
                arrival_at="2026-08-01T09:00:00+08:00",
                departure_at="2026-08-02T08:00:00+08:00",
            )
        )
    )
    last_day = result.itinerary.days[-1]
    assert last_day.day_type == "DEPARTURE_DAY"
    for activity in last_day.activities:
        assert activity.end_time.astimezone(CHINA_TIME_ZONE).time() <= time(8, 0)
    departure_activity = next(a for a in last_day.activities if a.kind == "DEPARTURE")
    assert departure_activity.end_time.astimezone(CHINA_TIME_ZONE).time() == time(8, 0)


def test_real_route_duration_never_pushes_departure_past_snapshot_boundary() -> None:
    """The route fit pass must respect the user's latest departure time.

    This reproduces the real-user failure where a route refresh moved the
    fixed departure node from 10:30 to 10:44 after scheduling had succeeded.
    """
    pois = (_poi("p1", "越秀公园"), _poi("p2", "陈家祠"), _poi("p3", "广州塔"))
    provider = AmapPlanningProvider(
        StaticMapProvider(pois),
        SuccessfulRouteProvider(duration_seconds=90 * 60),
    )

    with pytest.raises(PlanningInfeasibleError) as exc_info:
        asyncio.run(
            provider.plan(
                _command(
                    start="2026-08-01",
                    end="2026-08-01",
                    arrival={
                        "placeName": "广州站",
                        "time": "2026-08-01T09:00:00+08:00",
                    },
                    departure={
                        "placeName": "广州南站",
                        "time": "2026-08-01T10:30:00+08:00",
                    },
                )
            )
        )

    conflict = exc_info.value.conflicts[0]
    assert conflict.code == "INSUFFICIENT_DAY_CAPACITY"
    assert conflict.message == "实际交通时长无法在固定返程时间前完成"


def test_earlier_route_delay_never_moves_later_fixed_departure() -> None:
    """A delay before the last leg may move flexible activities, never the
    authoritative departure boundary itself."""
    pois = (_poi("p1", "越秀公园"), _poi("p2", "陈家祠"), _poi("p3", "广州塔"))
    provider = AmapPlanningProvider(StaticMapProvider(pois), FirstRouteDelayProvider())

    result = asyncio.run(
        provider.plan(
            _command(
                start="2026-08-01",
                end="2026-08-01",
                arrival={
                    "placeName": "广州站",
                    "time": "2026-08-01T09:00:00+08:00",
                },
                departure={
                    "placeName": "广州南站",
                    "time": "2026-08-01T18:00:00+08:00",
                },
            )
        )
    )

    departure = next(
        activity for activity in result.itinerary.days[0].activities if activity.kind == "DEPARTURE"
    )
    assert departure.end_time.astimezone(CHINA_TIME_ZONE).time() == time(18, 0)


def test_legacy_constraint_anchor_time_still_respected() -> None:
    """Legacy commands (no snapshot boundaries) keep the old anchor path."""
    pois = (_poi("p1", "越秀公园"), _poi("p2", "陈家祠"), _poi("p3", "广州塔"))
    result = asyncio.run(
        _provider(pois).plan(
            _command(
                arrival={"placeName": "广州站", "time": "2026-08-01T14:00:00+08:00"},
                departure={"placeName": "广州南站", "time": "2026-08-02T17:00:00+08:00"},
            )
        )
    )
    first_day = result.itinerary.days[0]
    arrival_activity = next(a for a in first_day.activities if a.kind == "ARRIVAL")
    assert arrival_activity.start_time.astimezone(CHINA_TIME_ZONE).time() == time(14, 0)


def test_must_visit_matches_only_the_named_place_not_sub_pois() -> None:
    """Regression: AMap child facilities (公交站/殿宇/停车场) must not be
    flagged as the must-visit place."""
    provider = AmapPlanningProvider(StaticMapProvider(()), SuccessfulRouteProvider())
    must_set = {"光孝寺"}
    assert provider._is_must_visit_poi(_poi("g1", "光孝寺"), must_set) is True
    assert provider._is_must_visit_poi(_poi("g2", "光孝寺(公交站)"), must_set) is False
    assert provider._is_must_visit_poi(_poi("g3", "光孝寺-六祖殿"), must_set) is False
    assert provider._is_must_visit_poi(_poi("g4", "光孝寺售票处"), must_set) is False
    assert provider._is_must_visit_poi(_poi("g5", "广州塔"), must_set) is False


def test_must_visit_matches_by_structured_provider_poi_id() -> None:
    """B13-D: a PlaceRef pins the exact provider POI, independent of the
    display name, so structured selection never degrades to text matching."""
    provider = AmapPlanningProvider(StaticMapProvider(()), SuccessfulRouteProvider())
    ref_ids = {"B0G1X002"}
    # The exact POI matches by id even when its title carries a suffix.
    assert provider._is_must_visit_poi(_poi("B0G1X002", "光孝寺(正门)"), set(), ref_ids) is True
    # A different POI with a matching name is NOT the selected place.
    assert provider._is_must_visit_poi(_poi("OTHER", "光孝寺"), set(), ref_ids) is False
    # Text matching still works independently when no refs are given.
    assert provider._is_must_visit_poi(_poi("OTHER", "光孝寺"), {"光孝寺"}) is True


# ── B4A: transient trip skeleton on PlanningResult ─────────────────────────


def test_planning_result_defaults_trip_skeleton_to_none() -> None:
    result = PlanningResult(provider="DEMO", itinerary=_minimal_itinerary())

    assert result.trip_skeleton is None


def test_demo_provider_result_projects_unresolved_skeleton() -> None:
    from trip_agent.infrastructure.demo.planning_provider import DemoPlanningProvider
    from trip_agent.planning.trip_skeleton import (
        AccommodationState,
        UnresolvedAccommodation,
    )

    result = asyncio.run(DemoPlanningProvider().plan(_command()))

    # B9.1: Demo now derives the same projection as every entry point, with
    # overnights strictly UNRESOLVED (never fabricated as confirmed).
    assert result.trip_skeleton is not None
    assert result.trip_skeleton.accommodation_states == (
        AccommodationState.UNRESOLVED,
        AccommodationState.UNRESOLVED,
    )
    for overnight in result.trip_skeleton.overnights:
        assert isinstance(overnight.accommodation, UnresolvedAccommodation)


def test_amap_result_carries_transient_trip_skeleton() -> None:
    pois = (_poi("p1", "越秀公园"), _poi("p2", "陈家祠"), _poi("p3", "广州塔"))
    result = asyncio.run(_provider(pois).plan(_command()))

    assert result.trip_skeleton is not None
    assert result.trip_skeleton.day_count == 3
    assert result.trip_skeleton.night_count == 2


def test_amap_skeleton_dates_match_itinerary_dates() -> None:
    pois = (_poi("p1", "越秀公园"), _poi("p2", "陈家祠"), _poi("p3", "广州塔"))
    result = asyncio.run(_provider(pois).plan(_command()))

    skeleton_dates = [day.date for day in result.trip_skeleton.days]
    itinerary_dates = [day.date for day in result.itinerary.days]
    assert skeleton_dates == itinerary_dates


def test_amap_skeleton_confirmed_when_hotel_resolved() -> None:
    hotel = _poi(
        "hotel-1", "广州花园酒店", district="越秀区", type_code="100000", type_name="住宿服务"
    )
    pois = (_poi("p1", "越秀公园"), _poi("p2", "陈家祠"))
    result = asyncio.run(
        _provider(pois, accommodation_poi=hotel).plan(
            _command(accommodation={"placeName": "广州花园酒店"})
        )
    )

    assert result.trip_skeleton is not None
    assert result.trip_skeleton.night_count == 2
    assert result.trip_skeleton.accommodation_states == (
        AccommodationState.CONFIRMED,
        AccommodationState.CONFIRMED,
    )
    for overnight in result.trip_skeleton.overnights:
        assert isinstance(overnight.accommodation, ConfirmedAccommodation)
        assert overnight.accommodation.provider_poi_id == "hotel-1"


def test_amap_skeleton_area_estimated_without_accommodation_request() -> None:
    pois = tuple(_poi(f"p{index}", f"景点{index}", district="越秀区") for index in range(1, 8))
    result = asyncio.run(_provider(pois).plan(_command(accommodation=None)))

    assert result.trip_skeleton is not None
    assert all(
        isinstance(overnight.accommodation, AreaEstimatedAccommodation)
        for overnight in result.trip_skeleton.overnights
    )
    assert result.trip_skeleton.accommodation_states == (
        AccommodationState.AREA_ESTIMATED,
        AccommodationState.AREA_ESTIMATED,
    )


def test_amap_skeleton_unresolved_when_no_region_available() -> None:
    pois = (
        _poi("p1", "越秀公园", district=""),
        _poi("p2", "陈家祠", district=""),
        _poi("p3", "广州塔", district=""),
    )
    result = asyncio.run(_provider(pois).plan(_command(accommodation=None)))

    assert result.trip_skeleton is not None
    assert all(
        isinstance(overnight.accommodation, UnresolvedAccommodation)
        for overnight in result.trip_skeleton.overnights
    )


def test_amap_single_day_skeleton_has_zero_nights() -> None:
    pois = (_poi("p1", "越秀公园"), _poi("p2", "陈家祠"))
    result = asyncio.run(_provider(pois).plan(_command(start="2026-08-01", end="2026-08-01")))

    assert result.trip_skeleton is not None
    assert result.trip_skeleton.day_count == 1
    assert result.trip_skeleton.night_count == 0
    assert result.trip_skeleton.overnights == ()


def test_completed_json_has_no_transient_fields() -> None:
    import json

    from trip_agent.worker.processor import process_planning_create

    pois = (_poi("p1", "越秀公园"), _poi("p2", "陈家祠"), _poi("p3", "广州塔"))
    completed = asyncio.run(process_planning_create(_command(), _provider(pois)))
    assert completed.schema_version == 11
    payload = json.loads(completed.model_dump_json(by_alias=True, exclude_none=True))
    assert "tripSkeleton" not in json.dumps(payload)
    assert "validationInputs" not in json.dumps(payload)


# ── B4A.1: strict accommodation anchor characterization ─────────────────────


def test_strict_anchor_failure_when_requested_hotel_not_found() -> None:
    """Characterization: AMap create fails hard on an unresolvable explicit
    accommodation request; it never returns an UNRESOLVED TripSkeleton."""
    pois = (_poi("p1", "越秀公园"), _poi("p2", "陈家祠"), _poi("p3", "广州塔"))
    with pytest.raises(PlanningInfeasibleError) as exc_info:
        asyncio.run(_provider(pois).plan(_command(accommodation={"placeName": "查无此酒店"})))

    codes = {conflict.code for conflict in exc_info.value.conflicts}
    assert "TRAVEL_ANCHOR_UNAVAILABLE" in codes


# ── B4B Phase 5: cross-layer standalone validation ─────────────────────────


def test_amap_confirmed_chain_validates_continuity_pass() -> None:
    from trip_agent.feasibility.models import FeasibilityStatus, RuleOutcome
    from trip_agent.feasibility.validator import validate_itinerary

    hotel = _poi(
        "hotel-1", "广州花园酒店", district="越秀区", type_code="100000", type_name="住宿服务"
    )
    meal = _poi(
        "r1", "老字号粤菜馆", district="越秀区", type_code="050000", type_name="餐饮服务"
    )
    pois = tuple(_poi(f"p{index}", f"景点{index}") for index in range(1, 8))
    command = _command(accommodation={"placeName": "广州花园酒店"})
    result = asyncio.run(
        _provider(
            pois,
            meal_pois=(
                meal,
                *tuple(
                    _poi(
                        f"r{index}",
                        f"meal-{index}",
                        type_code="050000",
                        type_name="餐饮服务",
                    )
                    for index in range(2, 7)
                ),
            ),
            accommodation_poi=hotel,
        ).plan(command)
    )

    report = validate_itinerary(
        command=command,
        itinerary=result.itinerary,
        report_id="3d76fb9e-362e-4b28-8a9e-18e8ac7050ad",
        validated_at=datetime(2026, 8, 9, 12, 0, tzinfo=UTC),
        trip_skeleton=result.trip_skeleton,
    )

    route = next(r for r in report.rule_results if r.rule_id == "ROUTE_ENDPOINT_CONTINUITY")
    cross = next(r for r in report.rule_results if r.rule_id == "CROSS_DAY_CONTINUITY")
    assert route.outcome is RuleOutcome.PASS
    assert cross.outcome is RuleOutcome.PASS
    # Four required rules remain unimplemented -> never VERIFIED.
    assert report.status is FeasibilityStatus.UNVERIFIED


def test_demo_chain_validates_unknown_and_unverified() -> None:
    from trip_agent.feasibility.models import FeasibilityStatus, RuleOutcome
    from trip_agent.feasibility.validator import validate_itinerary
    from trip_agent.infrastructure.demo.planning_provider import DemoPlanningProvider

    command = _command()
    result = asyncio.run(DemoPlanningProvider().plan(command))
    # B9.1: the Demo chain now carries its own projected skeleton/inputs.
    assert result.trip_skeleton is not None
    assert result.validation_inputs is not None

    report = validate_itinerary(
        command=command,
        itinerary=result.itinerary,
        report_id="3d76fb9e-362e-4b28-8a9e-18e8ac7050ad",
        validated_at=datetime(2026, 8, 9, 12, 0, tzinfo=UTC),
        trip_skeleton=result.trip_skeleton,
        validation_inputs=result.validation_inputs,
    )

    route = next(r for r in report.rule_results if r.rule_id == "ROUTE_ENDPOINT_CONTINUITY")
    cross = next(r for r in report.rule_results if r.rule_id == "CROSS_DAY_CONTINUITY")
    # Demo never resolves real restaurants or real route evidence, so the
    # route rule can never PASS; with the projected skeleton the cross-day
    # rule stays UNKNOWN.  Either way the report must stay UNVERIFIED.
    assert route.outcome is not RuleOutcome.PASS
    assert cross.outcome is RuleOutcome.UNKNOWN
    assert report.status is FeasibilityStatus.UNVERIFIED


# ── B5 Phase 8: transient validation inputs on PlanningResult ──────────────


def test_amap_result_carries_validation_inputs() -> None:
    from trip_agent.feasibility.inputs import MealProjectionState

    pois = tuple(_poi(f"p{index}", f"景点{index}") for index in range(1, 8))
    result = asyncio.run(_provider(pois).plan(_command()))

    assert result.validation_inputs is not None
    assert result.validation_inputs.meal_projection_state is MealProjectionState.COMPLETE
    assert len(result.validation_inputs.visit_duration_bindings) > 0


def test_amap_standalone_validation_is_unverified_with_unknown_evidence() -> None:
    from trip_agent.feasibility.models import FeasibilityStatus, RuleOutcome
    from trip_agent.feasibility.validator import validate_itinerary

    meal = _poi("r1", "老字号粤菜馆", district="越秀区")
    pois = tuple(_poi(f"p{index}", f"景点{index}") for index in range(1, 8))
    command = _command()
    result = asyncio.run(_provider(pois, meal_pois=(meal,)).plan(command))

    report = validate_itinerary(
        command=command,
        itinerary=result.itinerary,
        report_id="3d76fb9e-362e-4b28-8a9e-18e8ac7050ad",
        validated_at=datetime(2026, 8, 9, 12, 0, tzinfo=UTC),
        trip_skeleton=result.trip_skeleton,
        validation_inputs=result.validation_inputs,
    )

    opening = next(r for r in report.rule_results if r.rule_id == "OPENING_HOURS")
    duration = next(r for r in report.rule_results if r.rule_id == "VISIT_DURATION")
    cross = next(r for r in report.rule_results if r.rule_id == "CROSS_DAY_CONTINUITY")
    # AMap evidence is category/provider level: never hard-eligible; without
    # a confirmed hotel the cross-day rule is UNKNOWN too.
    assert opening.outcome is RuleOutcome.UNKNOWN
    assert duration.outcome is RuleOutcome.UNKNOWN
    assert cross.outcome is RuleOutcome.UNKNOWN
    assert report.status is FeasibilityStatus.UNVERIFIED
    assert report.missing_required_rule_ids == ()


def test_amap_explicit_breakfast_window_fails_without_breakfast_placement() -> None:
    from trip_agent.feasibility.models import FeasibilityStatus, RuleOutcome
    from trip_agent.feasibility.validator import validate_itinerary

    meal = _poi("r1", "老字号粤菜馆", district="越秀区")
    pois = tuple(_poi(f"p{index}", f"景点{index}") for index in range(1, 8))
    command = _command()
    # Add an explicit breakfast window; AMap schedules no breakfast.
    raw = command.model_dump(by_alias=True)
    raw["payload"]["trip"]["constraints"]["mealWindows"] = [
        {"mealType": "BREAKFAST", "startTime": "08:00", "endTime": "09:00"}
    ]
    from trip_agent.worker.contracts import PlanningCreateCommand

    breakfast_command = PlanningCreateCommand.model_validate(raw)
    result = asyncio.run(_provider(pois, meal_pois=(meal,)).plan(breakfast_command))

    report = validate_itinerary(
        command=breakfast_command,
        itinerary=result.itinerary,
        report_id="3d76fb9e-362e-4b28-8a9e-18e8ac7050ad",
        validated_at=datetime(2026, 8, 9, 12, 0, tzinfo=UTC),
        trip_skeleton=result.trip_skeleton,
        validation_inputs=result.validation_inputs,
    )

    meal_window = next(r for r in report.rule_results if r.rule_id == "MEAL_WINDOW")
    assert meal_window.outcome is RuleOutcome.FAIL
    assert report.status is FeasibilityStatus.NEEDS_REPAIR


def test_completed_has_evaluation() -> None:
    import json

    from trip_agent.worker.processor import process_planning_create

    pois = tuple(_poi(f"p{index}", f"景点{index}") for index in range(1, 8))
    completed = asyncio.run(process_planning_create(_command(), _provider(pois)))
    # B16: UNVERIFIED report without blocker -> v10 completed (with evaluation).
    assert completed.schema_version == 11
    payload = json.loads(completed.model_dump_json(by_alias=True, exclude_none=True))
    assert "evaluation" in json.dumps(payload)
    assert payload["payload"]["feasibilityReport"]["status"] == "UNVERIFIED"
    assert payload["payload"]["hasBlocker"] is False


# ── B14_FIX R5 (D05): real stage boundaries emit progress events ────────────


def test_plan_reports_real_stage_boundaries() -> None:
    """The REAL provider must emit a progress event at every real execution
    boundary: POI recall, candidate ranking, route calculation and constraint
    solving.  The UI renders stages without an event as "未触发" — never as
    "未执行" when the provider actually ran them.
    """
    from trip_agent.worker.progress import planning_progress_reporting

    pois = (_poi("p1", "越秀公园"), _poi("p2", "陈家祠"), _poi("p3", "广州塔"))
    provider = _provider(pois)
    stages: list[str] = []

    async def _reporter(stage, message, statistics=None):
        stages.append(stage)

    async def _run() -> None:
        async with planning_progress_reporting(_reporter):
            await provider.plan(_command())

    asyncio.run(_run())

    assert stages, "provider must report progress"
    assert "POI_RECALLING" in stages
    assert "CANDIDATES_RANKING" in stages
    assert "ROUTES_CALCULATING" in stages
    assert "CONSTRAINTS_SOLVING" in stages
    # Monotonic with the published stage order (regressive stages are dropped
    # by the publisher, so a well-behaved provider never goes backwards).
    order = (
        "TASK_ACCEPTED",
        "CONTEXT_VALIDATING",
        "CITY_FACTS_LOADING",
        "POI_RECALLING",
        "CANDIDATES_RANKING",
        "ROUTES_CALCULATING",
        "CONSTRAINTS_SOLVING",
        "REPAIRING",
        "KNOWLEDGE_RETRIEVING",
        "RESULT_EXPLAINING",
        "RESULT_PUBLISHING",
    )
    ranks = [order.index(stage) for stage in stages]
    assert ranks == sorted(ranks)


def test_completion_carries_accommodation_status() -> None:
    """B19-E: the emitted completion itinerary carries the accommodation
    resolution status.  DEMO keeps the name-only hotel label and projects
    UNRESOLVED — it never fabricates a confirmation."""
    from trip_agent.infrastructure.demo.planning_provider import DemoPlanningProvider
    from trip_agent.worker.processor import process_planning_create

    command = _command(accommodation={"placeName": "白天鹅宾馆"})
    completed = asyncio.run(process_planning_create(command, DemoPlanningProvider()))

    acc = completed.payload.itinerary.accommodation
    assert acc is not None
    assert acc.status == "UNRESOLVED"
    assert acc.place_name == "白天鹅宾馆"


def test_completion_without_accommodation_omits_status() -> None:
    from trip_agent.infrastructure.demo.planning_provider import DemoPlanningProvider
    from trip_agent.worker.processor import process_planning_create

    command = _command()
    completed = asyncio.run(process_planning_create(command, DemoPlanningProvider()))
    assert completed.payload.itinerary.accommodation is None
