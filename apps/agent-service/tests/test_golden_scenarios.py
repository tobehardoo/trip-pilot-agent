"""B5 golden-scenario semantic verification of the daily-skeleton producer.

These are the four first-round semantic scenarios; they are NOT the only gate
for removing the legacy two-activity path (see B6: full-suite + 10 cities x 3
rounds must also pass).
"""

import asyncio
from copy import deepcopy
from datetime import UTC, datetime

from test_planning_worker import COMMAND

from trip_agent.infrastructure.amap.planning_provider import AmapPlanningProvider
from trip_agent.providers.map import Coordinates, Poi, ProviderSuccess
from trip_agent.providers.route import RoutePlan, RouteStep
from trip_agent.worker.contracts import PlanningCreateCommand


def _poi(provider_id: str, name: str, *, city: str = "广州市") -> Poi:
    return Poi(
        provider_id=provider_id,
        name=name,
        coordinates=Coordinates(longitude=113.31, latitude=23.13),
        type_name="风景名胜",
        type_code="110000",
        province="广东省",
        city=city,
        district="越秀区",
        address=f"{name}地址",
    )


class StaticMapProvider:
    def __init__(self, pois: tuple[Poi, ...], *, meal_keyword: str = "美食") -> None:
        self._pois = pois
        self._meal_keyword = meal_keyword

    async def search_pois(self, request: object):
        keyword = request.keyword
        if keyword in {"广州站", "广州南站"}:
            return self._success((_poi("anchor-station", keyword),))
        if keyword == self._meal_keyword or keyword.endswith(" 美食"):
            # No restaurant available in any scenario: meals stay as slots.
            return self._success(())
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
    destination: str,
    start: str,
    end: str,
    arrival: dict | None = None,
    departure: dict | None = None,
    preferences: list[str] | None = None,
    pace: str = "BALANCED",
    travelers: int = 1,
    traveler_type: str = "SOLO",
    must_visit: list[str] | None = None,
) -> PlanningCreateCommand:
    payload = deepcopy(COMMAND)
    payload["schemaVersion"] = 2
    payload["payload"]["trip"]["destination"] = destination
    payload["payload"]["trip"]["title"] = f"{destination} 行程"
    payload["payload"]["trip"]["startDate"] = start
    payload["payload"]["trip"]["endDate"] = end
    constraints = payload["payload"]["trip"]["constraints"]
    constraints["schemaVersion"] = 2
    constraints["preferences"] = preferences or ["历史文化"]
    constraints["pace"] = pace
    constraints["travelers"] = travelers
    constraints["travelerType"] = traveler_type
    constraints["arrival"] = arrival
    constraints["departure"] = departure
    constraints["mustVisitPlaces"] = must_visit or []
    constraints["avoidPlaces"] = []
    constraints["mealWindows"] = []
    constraints["mobilityLevel"] = "STANDARD"
    constraints["fixedSchedules"] = []
    return PlanningCreateCommand.model_validate(payload)


def _plan(command: PlanningCreateCommand):
    provider = AmapPlanningProvider(
        StaticMapProvider((
            _poi("p1", "陈家祠", city=command.payload.trip.destination),
            _poi("p2", "越秀公园", city=command.payload.trip.destination),
            _poi("p3", "广州塔", city=command.payload.trip.destination),
            _poi("m1", "省博物馆", city=command.payload.trip.destination),
        )),
        SuccessfulRouteProvider(),
    )
    return asyncio.run(provider.plan(command))


def _kinds(day) -> set[str]:
    return {a.kind for a in day.activities}


# 1. 广州三日游，下午到达、下午离开，历史文化偏好 ---------------------------

def test_scenario_1_guangzhou_afternoon_arrival_and_departure() -> None:
    command = _command(
        destination="广州",
        start="2026-08-01",
        end="2026-08-03",
        arrival={"placeName": "广州站", "time": "2026-08-01T14:00:00+08:00"},
        departure={"placeName": "广州南站", "time": "2026-08-03T16:00:00+08:00"},
        preferences=["历史文化"],
    )
    result = _plan(command)

    assert [d.day_type for d in result.itinerary.days] == [
        "ARRIVAL_DAY", "FULL_DAY", "DEPARTURE_DAY",
    ]
    # Arrival day opens with a time-locked ARRIVAL anchor.
    first = result.itinerary.days[0]
    arrival = next(a for a in first.activities if a.kind == "ARRIVAL")
    assert arrival.time_fixed is True
    # Departure day ends with a time-locked DEPARTURE anchor.
    last = result.itinerary.days[-1]
    assert "DEPARTURE" in _kinds(last)
    # Middle FULL day is capacity-driven, not fixed at two attractions.
    middle = result.itinerary.days[1]
    attractions = [a for a in middle.activities if a.kind == "ATTRACTION"]
    assert 1 <= len(attractions) <= 3


# 2. 泰安三日游，其中一天泰山 -----------------------------------------------

def test_scenario_2_taian_with_mount_tai_day() -> None:
    provider = AmapPlanningProvider(
        StaticMapProvider((
            _poi("tai", "泰山", city="泰安市"),
            _poi("p1", "岱庙", city="泰安市"),
            _poi("p2", "天外村", city="泰安市"),
        )),
        SuccessfulRouteProvider(),
    )
    result = asyncio.run(
        provider.plan(_command(destination="泰安", start="2026-08-01", end="2026-08-03"))
    )

    special = [d for d in result.itinerary.days if d.day_type == "SPECIAL_ACTIVITY_DAY"]
    assert len(special) == 1
    experience = next(a for a in special[0].activities if a.kind == "EXPERIENCE")
    assert experience.title == "泰山"


# 3. 上海两日游，迪士尼占一天 -----------------------------------------------

def test_scenario_3_shanghai_with_disney_day() -> None:
    provider = AmapPlanningProvider(
        StaticMapProvider((
            _poi("d", "上海迪士尼乐园", city="上海市"),
            _poi("p1", "外滩", city="上海市"),
            _poi("p2", "城隍庙", city="上海市"),
        )),
        SuccessfulRouteProvider(),
    )
    result = asyncio.run(
        provider.plan(_command(destination="上海", start="2026-08-01", end="2026-08-02"))
    )

    special = [d for d in result.itinerary.days if d.day_type == "SPECIAL_ACTIVITY_DAY"]
    assert len(special) == 1
    experience = next(a for a in special[0].activities if a.kind == "EXPERIENCE")
    assert experience.title == "上海迪士尼乐园"


# 4. 带老人旅行，节奏轻松（无锚点）-----------------------------------------

def test_scenario_4_elderly_relaxed_no_anchors_not_fixed_two() -> None:
    provider = AmapPlanningProvider(
        StaticMapProvider((
            _poi("p1", "陈家祠", city="广州市"),
            _poi("p2", "越秀公园", city="广州市"),
            _poi("p3", "广州塔", city="广州市"),
            _poi("m1", "省博物馆", city="广州市"),
            _poi("p4", "光孝寺", city="广州市"),
            _poi("p5", "沙面岛", city="广州市"),
        )),
        SuccessfulRouteProvider(),
    )
    result = asyncio.run(
        provider.plan(
            _command(
                destination="广州",
                start="2026-08-01",
                end="2026-08-02",
                preferences=[],
                pace="RELAXED",
                traveler_type="FAMILY",
                travelers=3,
            )
        )
    )

    # No anchors => default window capacity planning, NOT the fixed-two model.
    for day in result.itinerary.days:
        assert day.day_type in {"FULL_DAY", "SPECIAL_ACTIVITY_DAY"}
        attractions = [a for a in day.activities if a.kind == "ATTRACTION"]
        assert len(attractions) <= 2, "relaxed elderly pace limits major activities"
    # Multi-day trip without a selected hotel: an unresolved accommodation
    # semantic anchor IS expected (authoritative domain semantics — it must
    # NOT be treated as "no accommodation").  The node must carry no fake
    # provider POI / coordinates.
    accommodation_nodes = [
        a for day in result.itinerary.days
        for a in day.activities
        if a.kind == "ACCOMMODATION"
    ]
    assert accommodation_nodes, "multi-day trip must keep an accommodation anchor"
    for node in accommodation_nodes:
        assert node.provider_poi_id is None
        assert node.coordinates is None
