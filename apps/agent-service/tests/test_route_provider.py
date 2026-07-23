import asyncio
import logging
from datetime import UTC, datetime, timedelta, timezone
from importlib import import_module
from importlib.util import find_spec
from typing import Any

import httpx
import pytest
from pydantic import ValidationError


def load_route_provider_module():
    assert find_spec("trip_agent.providers.route") is not None, "route provider is missing"
    return import_module("trip_agent.providers.route")


class FakeJsonCache:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.read_keys: list[str] = []
        self.writes: list[tuple[str, str, int]] = []

    async def get(self, key: str) -> str | None:
        self.read_keys.append(key)
        return self.values.get(key)

    async def set(self, key: str, value: str, *, ttl_seconds: int) -> None:
        self.values[key] = value
        self.writes.append((key, value, ttl_seconds))


class FailingJsonCache:
    def __init__(self, *, fail_reads: bool = False, fail_writes: bool = False) -> None:
        self.fail_reads = fail_reads
        self.fail_writes = fail_writes

    async def get(self, _: str) -> str | None:
        if self.fail_reads:
            raise RuntimeError("cache read failed")
        return None

    async def set(self, _: str, __: str, *, ttl_seconds: int) -> None:
        del ttl_seconds
        if self.fail_writes:
            raise RuntimeError("cache write failed")


def route_request(provider: Any, **overrides: object):
    values: dict[str, object] = {
        "origin": provider.Coordinates(longitude=113.261015, latitude=23.137823),
        "destination": provider.Coordinates(longitude=113.319263, latitude=23.109078),
        "mode": "WALKING",
        "departure_at": datetime(2026, 8, 1, 9, 15, tzinfo=UTC),
        "origin_poi_id": "origin-poi",
        "destination_poi_id": "destination-poi",
    }
    values.update(overrides)
    return provider.RouteRequest(**values)


def amap_route_response(**path_overrides: object) -> dict[str, object]:
    path: dict[str, object] = {
        "distance": "1850",
        "cost": {"duration": "1320"},
        "steps": [
            {
                "instruction": "Walk east",
                "step_distance": "500",
                "cost": {"duration": "360"},
                "polyline": "113.261015,23.137823;113.270000,23.130000",
            },
            {
                "instruction": "Arrive at the destination",
                "step_distance": "1350",
                "cost": {"duration": "960"},
                "polyline": "113.270000,23.130000;113.319263,23.109078",
            },
        ],
    }
    path.update(path_overrides)
    return {
        "status": "1",
        "info": "OK",
        "infocode": "10000",
        "count": "1",
        "route": {
            "origin": "113.261015,23.137823",
            "destination": "113.319263,23.109078",
            "paths": [path],
        },
    }


def run_amap_route(
    provider: Any,
    handler: Any,
    *,
    cache: Any = None,
) -> Any:
    async def run_scenario() -> Any:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            amap = provider.AmapRouteProvider(
                api_key="local-secret-key",
                http_client=client,
                cache=cache,
            )
            return await amap.get_route(route_request(provider))

    return asyncio.run(run_scenario())


def test_route_contract_represents_a_typed_walking_path() -> None:
    provider = load_route_provider_module()
    request = route_request(provider)
    step = provider.RouteStep(
        instruction="Walk east",
        distance_meters=420,
        duration_seconds=300,
        polyline=(request.origin, request.destination),
    )
    route = provider.RoutePlan(
        mode="WALKING",
        distance_meters=420,
        duration_seconds=300,
        steps=(step,),
        polyline=(request.origin, request.destination),
    )

    assert request.mode == "WALKING"
    assert request.origin_poi_id == "origin-poi"
    assert route.steps[0].instruction == "Walk east"
    assert route.polyline[-1] == request.destination


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("mode", "CYCLING"),
        ("departure_at", datetime(2026, 8, 1, 9, 15)),
        ("origin_poi_id", "x" * 101),
        ("destination_poi_id", "x" * 101),
    ],
)
def test_route_request_rejects_values_outside_the_phase_8_contract(
    field: str,
    value: object,
) -> None:
    provider = load_route_provider_module()

    with pytest.raises(ValidationError):
        route_request(provider, **{field: value})


def test_amap_walking_route_parses_polyline_and_uses_json_cache() -> None:
    provider = load_route_provider_module()
    cache = FakeJsonCache()
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=amap_route_response())

    async def run_scenario() -> tuple[Any, Any]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            amap = provider.AmapRouteProvider(
                api_key="local-secret-key",
                http_client=client,
                cache=cache,
                cache_ttl_seconds=3600,
            )
            request = route_request(provider)
            return await amap.get_route(request), await amap.get_route(request)

    first, cached = asyncio.run(run_scenario())

    assert isinstance(first, provider.ProviderSuccess)
    assert first.provider == "AMAP"
    assert first.cached is False
    assert first.estimated is False
    assert first.data.mode == "WALKING"
    assert first.data.distance_meters == 1850
    assert first.data.duration_seconds == 1320
    assert [step.duration_seconds for step in first.data.steps] == [360, 960]
    assert [(point.longitude, point.latitude) for point in first.data.polyline] == [
        (113.261015, 23.137823),
        (113.27, 23.13),
        (113.319263, 23.109078),
    ]
    assert isinstance(cached, provider.ProviderSuccess)
    assert cached.cached is True
    assert cached.data == first.data
    assert cached.fetched_at == first.fetched_at
    assert len(requests) == 1
    assert requests[0].url.path == "/v5/direction/walking"
    assert requests[0].url.params["origin"] == "113.261015,23.137823"
    assert requests[0].url.params["destination"] == "113.319263,23.109078"
    assert requests[0].url.params["origin_id"] == "origin-poi"
    assert requests[0].url.params["destination_id"] == "destination-poi"
    assert requests[0].url.params["show_fields"] == "cost,navi,polyline"
    assert requests[0].url.params["isindoor"] == "0"
    assert requests[0].url.params["output"] == "json"
    assert requests[0].url.params["key"] == "local-secret-key"
    cache_key, _, ttl_seconds = cache.writes[0]
    assert cache_key.startswith("map:route:v1:")
    assert ttl_seconds == 3600
    assert "local-secret-key" not in cache_key
    assert "113.261015" not in cache_key


def test_amap_driving_route_uses_vehicle_endpoint_and_preserves_mode() -> None:
    provider = load_route_provider_module()
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=amap_route_response())

    async def run_scenario() -> Any:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            amap = provider.AmapRouteProvider(
                api_key="local-secret-key",
                http_client=client,
            )
            return await amap.get_route(route_request(provider, mode="DRIVING"))

    result = asyncio.run(run_scenario())

    assert isinstance(result, provider.ProviderSuccess)
    assert result.data.mode == "DRIVING"
    assert requests[0].url.path == "/v5/direction/driving"
    assert requests[0].url.params["strategy"] == "32"
    assert "isindoor" not in requests[0].url.params


def test_amap_empty_walking_paths_is_a_typed_not_found_failure() -> None:
    provider = load_route_provider_module()
    payload = amap_route_response()
    payload["route"]["paths"] = []

    result = run_amap_route(provider, lambda _: httpx.Response(200, json=payload))

    assert isinstance(result, provider.ProviderFailure)
    assert result.error_code == "ROUTE_NOT_FOUND"
    assert result.retryable is False


@pytest.mark.parametrize(
    ("infocode", "expected_code", "retryable"),
    [
        ("10001", "PROVIDER_AUTH_FAILED", False),
        ("10004", "PROVIDER_RATE_LIMITED", True),
        ("10003", "PROVIDER_QUOTA_EXHAUSTED", False),
        ("10017", "PROVIDER_UNAVAILABLE", True),
        ("20000", "PROVIDER_REQUEST_INVALID", False),
        ("20003", "PROVIDER_ERROR", False),
        ("30000", "PROVIDER_UNAVAILABLE", True),
    ],
)
def test_amap_route_business_errors_are_mapped_to_stable_failures(
    infocode: str,
    expected_code: str,
    retryable: bool,
) -> None:
    provider = load_route_provider_module()
    payload = {
        "status": "0",
        "info": "provider rejected the request",
        "infocode": infocode,
        "count": "0",
    }

    result = run_amap_route(provider, lambda _: httpx.Response(200, json=payload))

    assert isinstance(result, provider.ProviderFailure)
    assert result.error_code == expected_code
    assert result.retryable is retryable
    assert "local-secret-key" not in result.error_message


@pytest.mark.parametrize(
    ("response_factory", "expected_code"),
    [
        (
            lambda request: (_ for _ in ()).throw(httpx.ReadTimeout("slow", request=request)),
            "PROVIDER_TIMEOUT",
        ),
        (
            lambda request: (_ for _ in ()).throw(
                httpx.ConnectError("connection failed", request=request)
            ),
            "PROVIDER_UNAVAILABLE",
        ),
        (lambda _: httpx.Response(503), "PROVIDER_UNAVAILABLE"),
    ],
)
def test_amap_route_transport_failures_are_retryable_results(
    response_factory: Any,
    expected_code: str,
) -> None:
    provider = load_route_provider_module()

    result = run_amap_route(provider, response_factory)

    assert isinstance(result, provider.ProviderFailure)
    assert result.error_code == expected_code
    assert result.retryable is True


def invalid_route_payload(case: str) -> dict[str, object]:
    payload = amap_route_response()
    if case == "missing-route":
        del payload["route"]
    elif case == "invalid-distance":
        payload["route"]["paths"][0]["distance"] = "not-a-number"
    elif case == "missing-step-cost":
        del payload["route"]["paths"][0]["steps"][0]["cost"]
    elif case == "invalid-polyline":
        payload["route"]["paths"][0]["steps"][0]["polyline"] = "not-a-coordinate"
    elif case == "negative-duration":
        payload["route"]["paths"][0]["cost"]["duration"] = "-1"
    elif case == "long-instruction":
        payload["route"]["paths"][0]["steps"][0]["instruction"] = "x" * 301
    elif case == "out-of-range-coordinate":
        payload["route"]["paths"][0]["steps"][0]["polyline"] = "181,23"
    else:
        raise AssertionError(f"unknown invalid route case: {case}")
    return payload


@pytest.mark.parametrize(
    "case",
    [
        "missing-route",
        "invalid-distance",
        "missing-step-cost",
        "invalid-polyline",
        "negative-duration",
        "long-instruction",
        "out-of-range-coordinate",
    ],
)
def test_amap_invalid_route_payload_is_reported_as_a_schema_change(case: str) -> None:
    provider = load_route_provider_module()

    result = run_amap_route(
        provider,
        lambda _: httpx.Response(200, json=invalid_route_payload(case)),
    )

    assert isinstance(result, provider.ProviderFailure)
    assert result.error_code == "PROVIDER_SCHEMA_CHANGED"
    assert result.retryable is False


def test_amap_invalid_route_json_is_reported_as_a_schema_change() -> None:
    provider = load_route_provider_module()

    result = run_amap_route(provider, lambda _: httpx.Response(200, content=b"not-json"))

    assert isinstance(result, provider.ProviderFailure)
    assert result.error_code == "PROVIDER_SCHEMA_CHANGED"


def test_route_cache_key_buckets_time_and_distinguishes_provider_poi_ids() -> None:
    provider = load_route_provider_module()
    request = route_request(provider)
    same_hour = route_request(
        provider,
        departure_at=request.departure_at + timedelta(minutes=30),
    )
    next_hour = route_request(
        provider,
        departure_at=request.departure_at + timedelta(hours=1),
    )
    different_origin = route_request(
        provider,
        origin=provider.Coordinates(longitude=113.262, latitude=23.138),
    )
    different_destination = route_request(
        provider,
        destination=provider.Coordinates(longitude=113.32, latitude=23.11),
    )
    different_poi = route_request(provider, destination_poi_id="another-destination")
    same_instant = route_request(
        provider,
        departure_at=request.departure_at.astimezone(timezone(timedelta(hours=8))),
    )

    base_key = provider.AmapRouteProvider._cache_key(request)

    assert provider.AmapRouteProvider._cache_key(same_hour) == base_key
    assert provider.AmapRouteProvider._cache_key(same_instant) == base_key
    assert provider.AmapRouteProvider._cache_key(next_hour) != base_key
    assert provider.AmapRouteProvider._cache_key(different_origin) != base_key
    assert provider.AmapRouteProvider._cache_key(different_destination) != base_key
    assert provider.AmapRouteProvider._cache_key(different_poi) != base_key


@pytest.mark.parametrize(
    "cache",
    [FailingJsonCache(fail_reads=True), FailingJsonCache(fail_writes=True)],
)
def test_amap_route_cache_failures_degrade_to_a_live_response(cache: Any) -> None:
    provider = load_route_provider_module()

    result = run_amap_route(
        provider,
        lambda _: httpx.Response(200, json=amap_route_response()),
        cache=cache,
    )

    assert isinstance(result, provider.ProviderSuccess)
    assert result.cached is False


def test_amap_corrupt_route_cache_is_replaced_from_the_live_provider() -> None:
    provider = load_route_provider_module()
    cache = FakeJsonCache()
    request = route_request(provider)
    cache.values[provider.AmapRouteProvider._cache_key(request)] = "not-json"
    calls = 0

    def handle(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=amap_route_response())

    result = run_amap_route(provider, handle, cache=cache)

    assert isinstance(result, provider.ProviderSuccess)
    assert calls == 1
    assert cache.writes


def test_amap_route_omits_absent_optional_poi_ids() -> None:
    provider = load_route_provider_module()
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=amap_route_response())

    async def run_scenario() -> Any:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            amap = provider.AmapRouteProvider(api_key="local-secret-key", http_client=client)
            return await amap.get_route(
                route_request(
                    provider,
                    origin_poi_id=None,
                    destination_poi_id=None,
                )
            )

    result = asyncio.run(run_scenario())

    assert isinstance(result, provider.ProviderSuccess)
    assert "origin_id" not in requests[0].url.params
    assert "destination_id" not in requests[0].url.params


def test_amap_route_httpx_info_log_redacts_the_api_key(
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider = load_route_provider_module()
    secret = "route-key-that-must-not-appear"
    caplog.set_level(logging.INFO, logger="httpx")

    async def run_scenario() -> Any:
        transport = httpx.MockTransport(
            lambda _: httpx.Response(200, json=amap_route_response())
        )
        async with httpx.AsyncClient(transport=transport) as client:
            amap = provider.AmapRouteProvider(api_key=secret, http_client=client)
            return await amap.get_route(route_request(provider))

    result = asyncio.run(run_scenario())

    assert isinstance(result, provider.ProviderSuccess)
    assert secret not in caplog.text
    assert "REDACTED" in caplog.text


def test_demo_route_provider_returns_a_deterministic_estimate() -> None:
    provider = load_route_provider_module()
    request = route_request(provider)

    first = asyncio.run(provider.DemoRouteProvider().get_route(request))
    second = asyncio.run(provider.DemoRouteProvider().get_route(request))

    assert isinstance(first, provider.ProviderSuccess)
    assert first.provider == "DEMO"
    assert first.estimated is True
    assert first.cached is False
    assert first.data == second.data
    assert first.data.distance_meters > 0
    assert first.data.duration_seconds > 0
    assert first.data.polyline == (request.origin, request.destination)
    assert len(first.data.steps) == 1


def test_demo_route_provider_handles_distant_valid_coordinates() -> None:
    provider = load_route_provider_module()
    request = route_request(
        provider,
        origin=provider.Coordinates(longitude=-90, latitude=0),
        destination=provider.Coordinates(longitude=90, latitude=0),
    )

    result = asyncio.run(provider.DemoRouteProvider().get_route(request))

    assert isinstance(result, provider.ProviderSuccess)
    assert result.data.distance_meters > 20_000_000
    assert result.data.duration_seconds > 1_000_000


@pytest.mark.parametrize(
    ("status_code", "expected_code", "retryable"),
    [
        (408, "PROVIDER_TIMEOUT", True),
        (401, "PROVIDER_AUTH_FAILED", False),
        (403, "PROVIDER_AUTH_FAILED", False),
        (429, "PROVIDER_RATE_LIMITED", True),
        (400, "PROVIDER_ERROR", False),
    ],
)
def test_amap_route_http_statuses_map_to_stable_failures(
    status_code: int,
    expected_code: str,
    retryable: bool,
) -> None:
    provider = load_route_provider_module()

    result = run_amap_route(provider, lambda _: httpx.Response(status_code))

    assert isinstance(result, provider.ProviderFailure)
    assert result.error_code == expected_code
    assert result.retryable is retryable


@pytest.mark.parametrize(
    ("api_key", "cache_ttl_seconds"),
    [("", 3600), ("local-key", 0), ("local-key", -1)],
)
def test_amap_route_provider_rejects_invalid_configuration(
    api_key: str,
    cache_ttl_seconds: int,
) -> None:
    provider = load_route_provider_module()

    with pytest.raises(ValueError):
        provider.AmapRouteProvider(
            api_key=api_key,
            http_client=object(),
            cache_ttl_seconds=cache_ttl_seconds,
        )
