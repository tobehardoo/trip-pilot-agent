"""B17 — bounded repair window relaxation on the departure day.

Gate: relaxation may only pull a SYSTEM-DEFAULT start boundary earlier;
user-derived boundaries (arrival/departure anchors, fixed schedules, meal
hard windows) are never moved.  The relaxation is bounded (30-min steps down
to 07:00) and the plan fails closed when even the floor window cannot fit
the real transit time.
"""

import asyncio
from copy import deepcopy
from datetime import UTC, datetime

import pytest
from test_planning_worker import COMMAND

from trip_agent.domain.planning.protocols import PlanningInfeasibleError
from trip_agent.infrastructure.amap.planning_provider import AmapPlanningProvider
from trip_agent.providers.map import Coordinates, Poi, ProviderSuccess
from trip_agent.providers.route import RoutePlan, RouteStep
from trip_agent.worker.contracts import PlanningCreateCommand


def _poi(provider_id: str, name: str, *, address: str | None = None) -> Poi:
    return Poi(
        provider_id=provider_id,
        name=name,
        coordinates=Coordinates(longitude=113.31, latitude=23.13),
        type_name="风景名胜",
        type_code="110000",
        province="广东省",
        city="广州市",
        district="越秀区",
        address=address if address is not None else f"{name}地址",
    )


class _MapProvider:
    """One must-visit attraction, an anchor station, and (optionally) a
    restaurant so meal slots resolve to a routable POI."""

    def __init__(
        self,
        *,
        with_restaurant: bool,
        empty_address_ids: frozenset[str] = frozenset(),
    ) -> None:
        self._with_restaurant = with_restaurant
        self._empty_address_ids = empty_address_ids

    async def search_pois(self, request: object):
        keyword = request.keyword
        if keyword in {"广州站", "广州南站"}:
            poi = _poi("anchor-station", keyword)
            if "anchor-station" in self._empty_address_ids:
                poi = _poi("anchor-station", keyword, address="")
            return self._ok((poi,))
        if keyword == "美食" or keyword.endswith(" 美食"):
            if self._with_restaurant:
                return self._ok((_poi("restaurant", "本地餐厅"),))
            return self._ok(())
        return self._ok((_poi("p2", "陈家祠"),))

    @staticmethod
    def _ok(pois: tuple[Poi, ...]) -> ProviderSuccess[tuple[Poi, ...]]:
        return ProviderSuccess(
            data=pois,
            provider="AMAP",
            latency_ms=1,
            cached=False,
            fetched_at=datetime(2026, 8, 1, tzinfo=UTC),
            estimated=False,
        )


class _TimedRoutes:
    """Deterministic route durations keyed by (origin_id, destination_id).

    Any pair not listed gets a short 5-minute hop so only the tuned legs
    control the timing boundary."""

    def __init__(self, durations: dict[tuple[str, str], int]) -> None:
        self.durations = durations
        self.requests: list[object] = []

    async def get_route(self, request: object):
        self.requests.append(request)
        origin_id = getattr(request, "origin_poi_id", None) or ""
        destination_id = getattr(request, "destination_poi_id", None) or ""
        duration_seconds = self.durations.get((origin_id, destination_id), 300)
        return ProviderSuccess(
            data=RoutePlan(
                mode="DRIVING",
                distance_meters=1000,
                duration_seconds=duration_seconds,
                steps=(
                    RouteStep(
                        instruction="drive",
                        distance_meters=1000,
                        duration_seconds=duration_seconds,
                        polyline=(request.origin, request.destination),
                    ),
                ),
                polyline=(request.origin, request.destination),
            ),
            provider="AMAP",
            latency_ms=1,
            cached=False,
            fetched_at=datetime(2026, 8, 1, tzinfo=UTC),
            estimated=False,
        )


def _command(*, lunch: dict | None = None) -> PlanningCreateCommand:
    payload = deepcopy(COMMAND)
    payload["schemaVersion"] = 2
    trip = payload["payload"]["trip"]
    trip["destination"] = "广州"
    trip["title"] = "广州 行程"
    trip["startDate"] = "2026-08-01"
    trip["endDate"] = "2026-08-02"
    constraints = trip["constraints"]
    constraints["schemaVersion"] = 2
    constraints["preferences"] = ["历史文化"]
    constraints["pace"] = "BALANCED"
    constraints["travelers"] = 1
    constraints["travelerType"] = "SOLO"
    constraints["arrival"] = {
        "placeName": "广州站",
        # 功能③（2026-09）默认日终 21:00 后，18:00 到达日会获得晚间容量并吸走
        # 必去景点。钉在默认日终之后的 21:00，让到达日仅剩缓冲窗，保持本文件
        # 要验证的场景：景点被迫落在离开日，触发有界松弛。
        "time": "2026-08-01T21:00:00+08:00",
    }
    constraints["departure"] = {
        "placeName": "广州南站",
        "time": "2026-08-02T16:00:00+08:00",
    }
    constraints["mustVisitPlaces"] = ["陈家祠"]
    constraints["avoidPlaces"] = []
    constraints["mealWindows"] = [lunch] if lunch else []
    constraints["mobilityLevel"] = "STANDARD"
    constraints["fixedSchedules"] = []
    return PlanningCreateCommand.model_validate(payload)


def _plan(
    command: PlanningCreateCommand,
    *,
    with_restaurant: bool = False,
    durations: dict[tuple[str, str], int] | None = None,
    empty_address_ids: frozenset[str] = frozenset(),
):
    provider = AmapPlanningProvider(
        _MapProvider(with_restaurant=with_restaurant, empty_address_ids=empty_address_ids),
        _TimedRoutes(durations or {}),
    )
    return asyncio.run(provider.plan(command))


# 1. 末日"酒店→景点→机场"超时：可选删除穷尽后，有界松弛把系统默认 09:00
#    提前到 08:30，行程成功且不越过固定离开缓冲。

def test_departure_day_relaxes_system_default_start_after_capacity_repair_exhausted() -> None:
    command = _command(
        lunch={"mealType": "LUNCH", "startTime": "12:00", "endTime": "13:00", "source": "DISABLED"}
    )
    result = _plan(
        command,
        durations={("p2", "anchor-station"): 18_000},  # 5h to the airport
    )

    day = result.itinerary.days[-1]
    departure = next(a for a in day.activities if a.kind == "DEPARTURE")
    # Departure 16:00 keeps its fixed 60-min buffer: [15:00, 16:00].
    assert departure.start_time.hour == 15
    assert departure.start_time.minute == 0
    p2 = next(a for a in day.activities if a.kind == "ATTRACTION")
    assert p2.title == "陈家祠"
    # The start boundary was pulled earlier than the 09:00 default.
    assert p2.start_time.hour < 9
    assert p2.end_time <= departure.start_time
    assert day.transit_legs


# 2. 最早可松弛时刻（07:00）仍不够：保持 NO_FEASIBLE_ITINERARY，不伪装成功。

def test_departure_day_fails_closed_when_floor_window_is_still_insufficient() -> None:
    command = _command(
        lunch={"mealType": "LUNCH", "startTime": "12:00", "endTime": "13:00", "source": "DISABLED"}
    )
    with pytest.raises(PlanningInfeasibleError) as excinfo:
        _plan(
            command,
            durations={("p2", "anchor-station"): 28_800},  # 8h: > floor-window gap
        )

    assert any(
        conflict.code == "INSUFFICIENT_DAY_CAPACITY" for conflict in excinfo.value.conflicts
    )


# 3. 松弛期间用户的 meal hard window 分毫不动：午餐仍锁定在 11:00-12:00，
#    且必去景点被安排在窗口之前。

def test_relaxation_never_moves_user_meal_hard_window() -> None:
    command = _command(
        lunch={"mealType": "LUNCH", "startTime": "11:00", "endTime": "12:00", "source": "USER"}
    )
    result = _plan(
        command,
        with_restaurant=True,
        durations={
            ("p2", "restaurant"): 3_600,  # 60min: shifts lunch unless the day starts earlier
            ("restaurant", "anchor-station"): 10_800,  # 3h to the airport
        },
    )

    day = result.itinerary.days[-1]
    lunch = next(a for a in day.activities if a.kind == "MEAL")
    assert lunch.start_time.hour == 11 and lunch.start_time.minute == 0
    assert lunch.end_time.hour == 12 and lunch.end_time.minute == 0
    p2 = next(a for a in day.activities if a.kind == "ATTRACTION")
    assert p2.title == "陈家祠"
    assert p2.end_time <= lunch.start_time
    departure = next(a for a in day.activities if a.kind == "DEPARTURE")
    assert lunch.end_time <= departure.start_time


# 4. 真实 AMAP 地点可能返回空地址：空 address 不得让行程构造崩溃为
#    INTERNAL_PLANNING_FAILED（ValidationError），松弛路径应照常工作。

def test_empty_address_poi_does_not_break_activity_construction() -> None:
    command = _command(
        lunch={"mealType": "LUNCH", "startTime": "12:00", "endTime": "13:00", "source": "DISABLED"}
    )
    result = _plan(
        command,
        durations={("p2", "anchor-station"): 18_000},  # 5h to the airport
        empty_address_ids=frozenset({"anchor-station"}),
    )

    day = result.itinerary.days[-1]
    departure = next(a for a in day.activities if a.kind == "DEPARTURE")
    assert departure.start_time.hour == 15  # fixed departure buffer intact
    p2 = next(a for a in day.activities if a.kind == "ATTRACTION")
    assert p2.title == "陈家祠"
    assert p2.start_time.hour < 9  # relaxation still happened
    assert p2.end_time <= departure.start_time