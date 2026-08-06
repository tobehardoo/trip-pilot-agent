"""Tests for the daily-skeleton producer path (the production planning path)."""

import asyncio
from copy import deepcopy
from datetime import UTC, datetime

from test_planning_worker import COMMAND

from trip_agent.infrastructure.amap.planning_provider import AmapPlanningProvider
from trip_agent.providers.map import (
    Coordinates,
    Poi,
    ProviderSuccess,
)
from trip_agent.providers.route import RoutePlan, RouteStep
from trip_agent.worker.contracts import PlanningCreateCommand


def _poi(provider_id: str, name: str, *, district: str = "越秀区") -> Poi:
    return Poi(
        provider_id=provider_id,
        name=name,
        coordinates=Coordinates(longitude=113.31, latitude=23.13),
        type_name="风景名胜",
        type_code="110000",
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

    async def get_route(self, request: object):
        return ProviderSuccess(
            data=RoutePlan(
                mode="WALKING",
                distance_meters=1200,
                duration_seconds=900,
                steps=(
                    RouteStep(
                        instruction="Walk",
                        distance_meters=1200,
                        duration_seconds=900,
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
    constraints["fixedSchedules"] = []
    return PlanningCreateCommand.model_validate(payload)


def _provider(
    pois: tuple[Poi, ...],
    *,
    meal_pois: tuple[Poi, ...] = (),
    accommodation_poi: Poi | None = None,
) -> AmapPlanningProvider:
    return AmapPlanningProvider(
        StaticMapProvider(
            pois, meal_pois=meal_pois, accommodation_poi=accommodation_poi
        ),
        SuccessfulRouteProvider(),
    )


# ── skeleton behavior --------------------------------------------------------

def test_skeleton_emits_arrival_day_type_and_anchor_kind() -> None:
    pois = (_poi("p1", "越秀公园"), _poi("p2", "陈家祠"), _poi("p3", "广州塔"))
    result = asyncio.run(
        _provider(pois).plan(
            _command(
                arrival={"placeName": "广州站", "time": "2026-08-01T14:00:00+08:00"}
            )
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
            _command(
                departure={"placeName": "广州南站", "time": "2026-08-03T11:00:00+08:00"}
            )
        )
    )

    last_day = result.itinerary.days[-1]
    assert last_day.day_type == "DEPARTURE_DAY"
    departure_activity = next(a for a in last_day.activities if a.kind == "DEPARTURE")
    assert departure_activity.time_fixed is True


def test_skeleton_emits_unresolved_meal_without_fake_poi() -> None:
    # meal_pois empty => restaurant resolution fails => MEAL node without POI.
    pois = (_poi("p1", "越秀公园"), _poi("p2", "陈家祠"), _poi("p3", "广州塔"))
    result = asyncio.run(
        _provider(pois).plan(_command())
    )

    meal_activities = tuple(
        a for day in result.itinerary.days for a in day.activities if a.kind == "MEAL"
    )
    assert meal_activities, "a full day must reserve meal time"
    for activity in meal_activities:
        assert activity.provider_poi_id is None
        assert activity.coordinates is None
        assert "建议在当前区域自行选择餐馆" in activity.title


def test_skeleton_resolves_meal_when_restaurant_available() -> None:
    meal = _poi("r1", "老字号粤菜馆", district="越秀区")
    pois = (_poi("p1", "越秀公园"), _poi("p2", "陈家祠"), _poi("p3", "广州塔"))
    result = asyncio.run(
        _provider(pois, meal_pois=(meal,)).plan(_command())
    )

    meal_activities = tuple(
        a for day in result.itinerary.days for a in day.activities if a.kind == "MEAL"
    )
    assert meal_activities
    assert all(a.provider_poi_id == "r1" for a in meal_activities)


def test_skeleton_full_day_experience_becomes_special_day() -> None:
    mountain = _poi("exp-1", "长隆欢乐世界", district="番禺区")
    pois = (mountain, _poi("p1", "越秀公园"), _poi("p2", "陈家祠"))
    result = asyncio.run(
        _provider(pois).plan(_command())
    )

    special_days = [day for day in result.itinerary.days if day.day_type == "SPECIAL_ACTIVITY_DAY"]
    assert special_days
    experience = next(
        a for a in special_days[0].activities if a.kind == "EXPERIENCE"
    )
    assert experience.title == "长隆欢乐世界"


def test_skeleton_does_not_fabricate_hotel_when_accommodation_unknown() -> None:
    pois = (_poi("p1", "越秀公园"), _poi("p2", "陈家祠"), _poi("p3", "广州塔"))
    result = asyncio.run(_provider(pois).plan(_command()))

    accommodation_nodes = tuple(
        a for day in result.itinerary.days for a in day.activities if a.kind == "ACCOMMODATION"
    )
    assert accommodation_nodes == ()


def test_skeleton_emits_hotel_nodes_when_accommodation_known() -> None:
    hotel = _poi("hotel-1", "广州花园酒店", district="越秀区")
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
            "ARRIVAL_DAY", "FULL_DAY", "DEPARTURE_DAY", "SPECIAL_ACTIVITY_DAY",
        }
        for activity in day.activities:
            assert activity.kind in {
                "ATTRACTION", "EXPERIENCE", "MEAL",
                "ACCOMMODATION", "ARRIVAL", "DEPARTURE",
            }
            assert activity.time_fixed in {True, False}


# ── flag decoupling ----------------------------------------------------------

def test_skeleton_result_serializes_as_v8_schema_valid() -> None:
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
    assert completed.schema_version == 8

    payload = completed.model_dump_json(by_alias=True, exclude_none=True)
    schema = json.loads(
        Path("../../contracts/messaging/planning-completed-event-v8.schema.json")
        .read_text(encoding="utf-8")
    )
    jsonschema.validate(json.loads(payload), schema)


def test_producer_always_writes_v8() -> None:
    from trip_agent.worker.processor import process_planning_create

    pois = (_poi("p1", "越秀公园"), _poi("p2", "陈家祠"), _poi("p3", "广州塔"))
    command = _command()
    completed = asyncio.run(
        process_planning_create(command, _provider(pois))
    )
    assert completed.schema_version == 8


def test_demo_skeleton_classifies_days_and_marks_anchors() -> None:
    from trip_agent.infrastructure.demo.planning_provider import DemoPlanningProvider

    provider = DemoPlanningProvider()
    result = asyncio.run(
        provider.plan(
            _command(
                arrival={"placeName": "广州站", "time": "2026-08-01T16:00:00+08:00"}
            )
        )
    )
    first = result.itinerary.days[0]
    assert first.day_type == "ARRIVAL_DAY"
    assert any(a.kind == "ARRIVAL" and a.time_fixed for a in first.activities)
    assert result.itinerary.days[1].day_type == "FULL_DAY"
