"""B7: restaurant de-duplication is a soft preference, never a hard ban."""

import asyncio
from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal

from test_planning_worker import COMMAND

from trip_agent.infrastructure.amap.planning_provider import AmapPlanningProvider
from trip_agent.planning.daily_schedule import MealDemand
from trip_agent.providers.map import Coordinates, Poi, ProviderSuccess
from trip_agent.providers.route import RouteProvider
from trip_agent.worker.contracts import PlanningCreateCommand


def _poi(index: int, district: str = "天河区") -> Poi:
    return Poi(
        provider_id=f"rest-{index}",
        name=f"餐馆{index}",
        coordinates=Coordinates(
            longitude=Decimal("113") + index, latitude=Decimal("23") + index
        ),
        type_name="中餐厅",
        type_code="050100",
        province="广东省",
        city="广州市",
        district=district,
        address=f"地址{index}",
    )


class _MapProvider:
    def __init__(self, pois: tuple[Poi, ...]) -> None:
        self._pois = pois

    async def search_pois(self, request: object) -> ProviderSuccess:
        del request
        return ProviderSuccess(
            data=self._pois,
            provider="AMAP",
            latency_ms=1,
            cached=False,
            fetched_at=datetime(2026, 7, 17, tzinfo=UTC),
            estimated=False,
        )


class _NoRouteProvider(RouteProvider):
    async def get_route(self, request: object):
        raise AssertionError("meal resolution must not plan routes")


def _provider(pois: tuple[Poi, ...]) -> AmapPlanningProvider:
    return AmapPlanningProvider(_MapProvider(pois), _NoRouteProvider())


def _command() -> PlanningCreateCommand:
    payload = deepcopy(COMMAND)
    payload["payload"]["trip"]["destination"] = "广州"
    return PlanningCreateCommand.model_validate(payload)


def _meal(region: str | None = None) -> MealDemand:
    return MealDemand(
        meal_type="LUNCH", start_minute=720, end_minute=780, region=region
    )


def _resolve(provider, meal, used_today=frozenset(), used_previous=frozenset()):
    return asyncio.run(
        provider._resolve_meal_poi(meal, _command(), used_today, used_previous)
    )


def test_prefers_a_restaurant_not_used_same_day_or_previous_day():
    provider = _provider((_poi(1), _poi(2), _poi(3)))

    assert _resolve(provider, _meal()).provider_id == "rest-1"
    assert _resolve(
        provider, _meal(), used_today=frozenset({"rest-1"})
    ).provider_id == "rest-2"
    assert _resolve(
        provider, _meal(), used_today=frozenset({"rest-1"}), used_previous=frozenset({"rest-2"})
    ).provider_id == "rest-3"


def test_falls_back_to_a_duplicate_when_every_candidate_repeats():
    provider = _provider((_poi(1),))
    result = _resolve(provider, _meal(), used_today=frozenset({"rest-1"}))

    # 候选不足时允许重复，绝不删除餐饮时间窗口。
    assert result.provider_id == "rest-1"


def test_region_preference_outranks_dedup_for_the_same_region():
    # 候选 1 是天河，候选 2 是越秀；用户区域是天河，哪怕候选 1 当日已用也优先区域。
    provider = _provider((_poi(1, "天河区"), _poi(2, "越秀区")))
    result = _resolve(provider, _meal(region="天河区"), used_today=frozenset({"rest-1"}))

    assert result.provider_id == "rest-1"


def test_region_preference_keeps_dedup_among_region_matches():
    # 用户区域是天河，区域内候选 1 已用则选区域内候选 2，而不是区域外的候选。
    provider = _provider(
        (_poi(1, "天河区"), _poi(2, "天河区"), _poi(3, "越秀区"))
    )
    result = _resolve(provider, _meal(region="天河区"), used_today=frozenset({"rest-1"}))

    assert result.provider_id == "rest-2"


def test_unresolved_meal_keeps_the_time_window():
    provider = _provider(())
    assert _resolve(provider, _meal()) is None
