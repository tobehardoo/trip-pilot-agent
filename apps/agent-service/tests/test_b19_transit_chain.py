import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest

from trip_agent.domain.planning.protocols import PlanningProviderError
from trip_agent.domain.shared import MAX_ROUTE_CALLS_PER_PLAN
from trip_agent.infrastructure.amap.planning_provider import AmapPlanningProvider
from trip_agent.providers.errors import ProviderExecutionMode
from trip_agent.providers.map import ProviderSuccess
from trip_agent.providers.route import RoutePlan, RouteRequest, RouteStep


def transit_request(**overrides: object) -> RouteRequest:
    values: dict[str, object] = {
        "origin": RouteRequest.model_fields["origin"].annotation(
            longitude=113.261015, latitude=23.137823
        )
        if False
        else _coordinates(113.261015, 23.137823),
        "destination": _coordinates(113.319263, 23.109078),
        "mode": "TRANSIT",
        "city": "广州",
        "strategy": 0,
        "nightflag": 0,
        "departure_at": datetime(2026, 8, 1, 1, 15, tzinfo=UTC),
        "origin_poi_id": "origin-poi",
        "destination_poi_id": "destination-poi",
    }
    values.update(overrides)
    return RouteRequest(**values)


def _coordinates(longitude: float, latitude: float):
    from trip_agent.providers.map import Coordinates

    return Coordinates(longitude=longitude, latitude=latitude)


def driving_request(**overrides: object) -> RouteRequest:
    values: dict[str, object] = {
        "origin": _coordinates(113.261015, 23.137823),
        "destination": _coordinates(113.319263, 23.109078),
        "mode": "DRIVING",
        "departure_at": datetime(2026, 8, 1, 1, 15, tzinfo=UTC),
        "origin_poi_id": "origin-poi",
        "destination_poi_id": "destination-poi",
    }
    values.update(overrides)
    return RouteRequest(**values)


class RecordingRouteProvider:
    def __init__(self, mode: str = "DRIVING") -> None:
        self.mode = mode
        self.calls = 0
        self.requests: list[object] = []

    async def get_route(self, request: object):
        self.calls += 1
        self.requests.append(request)
        return ProviderSuccess(
            data=RoutePlan(
                mode=self.mode,
                distance_meters=1850,
                duration_seconds=1320,
                steps=(
                    RouteStep(
                        instruction="Route to the next activity",
                        distance_meters=1850,
                        duration_seconds=1320,
                        polyline=(request.origin, request.destination),
                    ),
                ),
                polyline=(request.origin, request.destination),
            ),
            provider="AMAP",
            latency_ms=2,
            cached=False,
            fetched_at=datetime(2026, 8, 1, 1, 16, tzinfo=UTC),
            estimated=False,
        )


class RecordingTransitRouteProvider:
    def __init__(self) -> None:
        self.calls = 0
        self.requests: list[object] = []

    async def get_route(self, request: object):
        self.calls += 1
        self.requests.append(request)
        return ProviderSuccess(
            data=RoutePlan(
                mode="TRANSIT",
                distance_meters=6085,
                duration_seconds=1250,
                steps=(
                    RouteStep(
                        instruction="Ride transit to the next activity",
                        distance_meters=6085,
                        duration_seconds=1250,
                        polyline=(request.origin, request.destination),
                    ),
                ),
                polyline=(request.origin, request.destination),
                walking_distance_meters=654,
                transfer_count=0,
            ),
            provider="AMAP",
            latency_ms=2,
            cached=False,
            fetched_at=datetime(2026, 8, 1, 1, 16, tzinfo=UTC),
            estimated=False,
        )


def build_provider(*, route_provider: RecordingRouteProvider, transit_route: object = None):
    kwargs: dict[str, object] = {}
    if transit_route is not None:
        kwargs["transit_route"] = transit_route
    return AmapPlanningProvider(
        map_provider=object(),
        route_provider=route_provider,
        provider_mode=ProviderExecutionMode.REAL_ONLY,
        **kwargs,
    )


def test_amap_planning_provider_accepts_a_transit_route_dependency() -> None:
    transit_provider = RecordingTransitRouteProvider()

    provider = build_provider(
        route_provider=RecordingRouteProvider(),
        transit_route=transit_provider,
    )

    assert provider._transit_route is transit_provider


def test_amap_planning_provider_dispatches_transit_to_the_transit_provider() -> None:
    transit_provider = RecordingTransitRouteProvider()
    route_provider = RecordingRouteProvider()
    provider = build_provider(
        route_provider=route_provider,
        transit_route=transit_provider,
    )
    request = transit_request()

    result = asyncio.run(provider._route(request))

    assert transit_provider.requests == [request]
    assert route_provider.requests == []
    assert result.data.mode == "TRANSIT"


def test_amap_planning_provider_fails_closed_without_a_transit_provider() -> None:
    provider = build_provider(route_provider=RecordingRouteProvider())

    with pytest.raises(PlanningProviderError):
        asyncio.run(provider._route(transit_request()))


def test_transit_and_driving_keep_separate_caches() -> None:
    transit_provider = RecordingTransitRouteProvider()
    route_provider = RecordingRouteProvider()
    provider = build_provider(
        route_provider=route_provider,
        transit_route=transit_provider,
    )
    cache: dict[Any, Any] = {}
    calls = [0]

    asyncio.run(provider._route_cached(transit_request(), cache, calls))
    asyncio.run(provider._route_cached(driving_request(), cache, calls))
    asyncio.run(provider._route_cached(transit_request(), cache, calls))
    asyncio.run(provider._route_cached(driving_request(), cache, calls))

    assert transit_provider.calls == 1
    assert route_provider.calls == 1
    assert len(cache) == 2


def test_transit_cache_key_buckets_departure_time_to_15_minutes() -> None:
    transit_provider = RecordingTransitRouteProvider()
    provider = build_provider(
        route_provider=RecordingRouteProvider(),
        transit_route=transit_provider,
    )
    cache: dict[Any, Any] = {}
    calls = [0]

    for minute in (0, 14, 15):
        departure = datetime(2026, 8, 1, 1, minute, tzinfo=UTC)
        asyncio.run(
            provider._route_cached(transit_request(departure_at=departure), cache, calls)
        )

    assert transit_provider.calls == 2


def test_transit_cache_key_includes_the_calendar_date() -> None:
    """The same HH:mm on different dates must not share a transit cache entry —
    night schedules / daily service differ, so the date is part of the key."""
    transit_provider = RecordingTransitRouteProvider()
    provider = build_provider(
        route_provider=RecordingRouteProvider(),
        transit_route=transit_provider,
    )
    cache: dict[Any, Any] = {}
    calls = [0]

    for day in (19, 20):
        departure = datetime(2026, 8, day, 1, 0, tzinfo=UTC)
        asyncio.run(
            provider._route_cached(transit_request(departure_at=departure), cache, calls)
        )

    assert transit_provider.calls == 2


def test_transit_cache_key_distinguishes_city_strategy_and_nightflag() -> None:
    transit_provider = RecordingTransitRouteProvider()
    provider = build_provider(
        route_provider=RecordingRouteProvider(),
        transit_route=transit_provider,
    )
    cache: dict[Any, Any] = {}
    calls = [0]

    for request in (
        transit_request(),
        transit_request(city="深圳"),
        transit_request(strategy=1),
        transit_request(nightflag=1),
    ):
        asyncio.run(provider._route_cached(request, cache, calls))

    assert transit_provider.calls == 4


def test_transit_and_driving_share_the_route_call_budget() -> None:
    transit_provider = RecordingTransitRouteProvider()
    route_provider = RecordingRouteProvider()
    provider = build_provider(
        route_provider=route_provider,
        transit_route=transit_provider,
    )
    cache: dict[Any, Any] = {}
    calls = [MAX_ROUTE_CALLS_PER_PLAN - 1]

    asyncio.run(provider._route_cached(transit_request(), cache, calls))

    with pytest.raises(PlanningProviderError, match="ROUTE_CALL_BUDGET_EXHAUSTED"):
        asyncio.run(provider._route_cached(driving_request(), cache, calls))