import asyncio
from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from test_planning_worker import COMMAND

from trip_agent.providers.map import Coordinates, Poi, ProviderSuccess
from trip_agent.providers.route import DemoRouteProvider
from trip_agent.worker.contracts import PlanningCreateCommand
from trip_agent.worker.processor import AmapPlanningProvider, PlanningInfeasibleError


def _command(*, budget: float, preferences: list[str]) -> PlanningCreateCommand:
    payload = deepcopy(COMMAND)
    payload["payload"]["trip"]["endDate"] = "2026-08-01"
    payload["payload"]["trip"]["constraints"]["budgetAmount"] = budget
    payload["payload"]["trip"]["constraints"]["preferences"] = preferences
    return PlanningCreateCommand.model_validate(payload)


def _poi(provider_id: str, name: str, longitude: float) -> Poi:
    return Poi(
        provider_id=provider_id,
        name=name,
        coordinates=Coordinates(longitude=longitude, latitude=23.13),
        type_name="风景名胜",
        type_code="110000",
        province="广东省",
        city="广州市",
        district="越秀区",
        address=f"{name}地址",
    )


class StaticMapProvider:
    def __init__(self, pois: tuple[Poi, ...]) -> None:
        self._pois = pois

    async def search_pois(self, request: object):
        del request
        return ProviderSuccess(
            data=self._pois,
            provider="AMAP",
            latency_ms=1,
            cached=False,
            fetched_at=datetime(2026, 7, 23, tzinfo=UTC),
            estimated=False,
        )


def test_amap_planner_enforces_budget_and_persists_nonzero_estimates() -> None:
    pois = (_poi("poi-1", "广州塔", 113.31), _poi("poi-2", "越秀公园", 113.32))
    affordable = _command(budget=500, preferences=[])

    result = asyncio.run(
        AmapPlanningProvider(StaticMapProvider(pois), DemoRouteProvider()).plan(affordable)
    )

    assert result.itinerary.estimated_total_cost == Decimal("200.00")
    assert [activity.estimated_cost for activity in result.itinerary.days[0].activities] == [
        Decimal("100.00"),
        Decimal("100.00"),
    ]

    over_budget = _command(budget=100, preferences=[])
    with pytest.raises(PlanningInfeasibleError) as failure:
        asyncio.run(
            AmapPlanningProvider(StaticMapProvider(pois), DemoRouteProvider()).plan(over_budget)
        )

    assert failure.value.conflicts[0].code == "BUDGET_EXCEEDED"
    assert failure.value.relaxations[0].code == "INCREASE_BUDGET"


def test_candidate_collection_continues_after_near_duplicate_places() -> None:
    duplicate_first = _poi("poi-a", "广州博物馆", 113.31)
    duplicate_second = _poi("poi-b", "广州博物馆", 113.31)
    alternative = _poi("poi-c", "广州塔", 113.32)

    class SequencedMapProvider:
        def __init__(self) -> None:
            self.keywords: list[str] = []

        async def search_pois(self, request: object):
            self.keywords.append(request.keyword)
            pois = (
                (duplicate_first, duplicate_second)
                if request.keyword == "博物馆"
                else (alternative,)
            )
            return ProviderSuccess(
                data=pois,
                provider="AMAP",
                latency_ms=1,
                cached=False,
                fetched_at=datetime(2026, 7, 23, tzinfo=UTC),
                estimated=False,
            )

    provider = SequencedMapProvider()
    result = asyncio.run(
        AmapPlanningProvider(provider, DemoRouteProvider()).plan(
            _command(budget=500, preferences=["博物馆"])
        )
    )

    assert result.provider == "AMAP"
    assert provider.keywords == ["博物馆", "景点"]
    assert {
        activity.provider_poi_id for activity in result.itinerary.days[0].activities
    } == {"poi-a", "poi-c"}
