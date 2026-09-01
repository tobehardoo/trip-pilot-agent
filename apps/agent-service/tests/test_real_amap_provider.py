import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from trip_agent.domain.planning.protocols import PlanningInfeasibleError
from trip_agent.infrastructure.amap.planning_provider import AmapPlanningProvider
from trip_agent.providers.map import AmapMapProvider, PoiSearchRequest, ProviderSuccess
from trip_agent.providers.route import AmapRouteProvider, RouteRequest
from trip_agent.worker.contracts import PlanningCreateCommand
from trip_agent.worker.runtime import WorkerSettings

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_REAL_PROVIDER_TESTS", "").lower() != "true",
    reason="set RUN_REAL_PROVIDER_TESTS=true to consume real AMap quota",
)

FIXTURE_DIRECTORY = Path(__file__).parent / "fixtures" / "real_provider"


def load_sample(name: str) -> dict[str, object]:
    return json.loads((FIXTURE_DIRECTORY / name).read_text(encoding="utf-8"))


def real_settings() -> WorkerSettings:
    return WorkerSettings(provider_mode="REAL_ONLY")


def test_real_amap_poi_and_routes_match_sample_a() -> None:
    sample = load_sample("guangzhou_day_a.json")
    settings = real_settings()
    key = settings.amap_web_service_key
    assert key is not None

    async def run_scenario() -> None:
        async with httpx.AsyncClient(timeout=settings.amap_timeout_seconds) as client:
            map_provider = AmapMapProvider(
                api_key=key.get_secret_value(),
                http_client=client,
            )
            route_provider = AmapRouteProvider(
                api_key=key.get_secret_value(),
                http_client=client,
            )
            places = {}
            for query in sample["poiQueries"]:
                result = await map_provider.search_pois(
                    PoiSearchRequest(city="广州", keyword=query, limit=5)
                )
                assert isinstance(result, ProviderSuccess), result
                assert result.provider == "AMAP"
                assert result.estimated is False
                assert result.data
                assert all(item.address is not None for item in result.data)
                places[query] = result.data[0]
                await asyncio.sleep(0.5)

            for route_check in sample["routeChecks"]:
                origin = places[route_check["origin"]]
                destination = places[route_check["destination"]]
                for mode in route_check["modes"]:
                    result = await route_provider.get_route(
                        RouteRequest(
                            origin=origin.coordinates,
                            destination=destination.coordinates,
                            origin_poi_id=origin.provider_id,
                            destination_poi_id=destination.provider_id,
                            mode=mode,
                            departure_at=datetime(2026, 9, 10, 10, tzinfo=UTC),
                        )
                    )
                    assert isinstance(result, ProviderSuccess), result
                    assert result.provider == "AMAP"
                    assert result.estimated is False
                    assert result.data.mode == mode
                    assert result.data.distance_meters > 0
                    assert result.data.duration_seconds > 0
                    assert result.data.polyline
                    await asyncio.sleep(0.5)

    asyncio.run(run_scenario())


def test_real_amap_planner_completes_sample_b_without_demo_routes() -> None:
    sample = load_sample("guangzhou_two_day_b.json")
    command = PlanningCreateCommand.model_validate(sample["command"])
    settings = real_settings()
    key = settings.amap_web_service_key
    assert key is not None

    async def run_scenario():
        async with httpx.AsyncClient(timeout=settings.amap_timeout_seconds) as client:
            map_provider = AmapMapProvider(api_key=key.get_secret_value(), http_client=client)
            route_provider = AmapRouteProvider(api_key=key.get_secret_value(), http_client=client)
            provider = AmapPlanningProvider(
                map_provider,
                route_provider,
                route_fallback=route_provider,
            )
            return await provider.plan(command)

    result = asyncio.run(run_scenario())
    activities = [activity for day in result.itinerary.days for activity in day.activities]
    transit_legs = [leg for day in result.itinerary.days for leg in day.transit_legs]

    assert result.provider == "AMAP"
    assert len(result.itinerary.days) == sample["expectations"]["dayCount"]
    assert len(activities) >= sample["expectations"]["minActivities"]
    assert any(sample["expectations"]["mustVisit"] in item.title for item in activities)
    assert len(transit_legs) >= sample["expectations"]["minTransitLegs"]
    assert all(leg.provider == "AMAP" and not leg.estimated for leg in transit_legs)
    assert all(leg.distance_meters > 0 and leg.duration_seconds > 0 for leg in transit_legs)
    assert all(leg.polyline for leg in transit_legs)


def test_real_amap_sample_c_is_explicitly_infeasible() -> None:
    sample = load_sample("guangzhou_infeasible_c.json")
    command = PlanningCreateCommand.model_validate(sample["command"])
    settings = real_settings()
    key = settings.amap_web_service_key
    assert key is not None

    async def run_scenario() -> None:
        async with httpx.AsyncClient(timeout=settings.amap_timeout_seconds) as client:
            map_provider = AmapMapProvider(api_key=key.get_secret_value(), http_client=client)
            route_provider = AmapRouteProvider(api_key=key.get_secret_value(), http_client=client)
            provider = AmapPlanningProvider(
                map_provider,
                route_provider,
                route_fallback=route_provider,
            )
            with pytest.raises(PlanningInfeasibleError) as failure:
                await provider.plan(command)
            assert failure.value.conflicts[0].code == sample["expectations"]["conflictCode"]

    asyncio.run(run_scenario())
