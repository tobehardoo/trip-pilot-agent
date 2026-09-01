import asyncio
import logging
from datetime import UTC, datetime, timedelta, timezone
from importlib import import_module
from importlib.util import find_spec
from typing import Any

import httpx
import pytest


def load_transit_provider_module():
    assert find_spec("trip_agent.providers._amap_transit") is not None, (
        "transit provider is missing"
    )
    return import_module("trip_agent.providers._amap_transit")


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


def transit_request(provider: Any, **overrides: object):
    values: dict[str, object] = {
        "origin": provider.Coordinates(longitude=113.261015, latitude=23.137823),
        "destination": provider.Coordinates(longitude=113.319263, latitude=23.109078),
        "mode": "TRANSIT",
        "city": "广州",
        "strategy": 0,
        "nightflag": 0,
        "departure_at": datetime(2026, 8, 1, 1, 15, tzinfo=UTC),
        "origin_poi_id": "origin-poi",
        "destination_poi_id": "destination-poi",
    }
    values.update(overrides)
    return provider.RouteRequest(**values)


def amap_transit_response(**path_overrides: object) -> dict[str, object]:
    path: dict[str, object] = {
        "cost": "2.0",
        "duration": "1250",
        "nightflag": "0",
        "restriction": "0",
        "walking_distance": "654",
        "distance": "6085",
        "segments": [
            {
                "walking": {
                    "distance": "400",
                    "duration": "400",
                    "steps": [
                        {
                            "instruction": "步行400米",
                            "distance": "400",
                            "polyline": "113.261015,23.137823;113.270000,23.130000",
                        }
                    ],
                },
                "bus": {"buslines": []},
                "taxi": [],
            },
            {
                "walking": [],
                "bus": {
                    "buslines": [
                        {
                            "name": "B1",
                            "type": "普通公交线路",
                            "distance": "3431",
                            "duration": "600",
                            "departure_stop": "Stop A",
                            "arrival_stop": "Stop B",
                            "via_num": "3",
                            "polyline": "113.270000,23.130000;113.319263,23.109078",
                        }
                    ]
                },
                "taxi": [],
            },
            {
                "walking": {
                    "distance": "2254",
                    "duration": "250",
                    "steps": [
                        {
                            "instruction": "步行2254米",
                            "distance": "2254",
                            "polyline": "113.319263,23.109078",
                        }
                    ],
                },
                "bus": {"buslines": []},
                "taxi": [],
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
            "transits": [path],
        },
    }


def metro_bus_transfer_fixture() -> dict[str, object]:
    return amap_transit_response(
        walking_distance="954",
        distance="13000",
        duration="2100",
        segments=[
            {
                "walking": {
                    "distance": "400",
                    "duration": "400",
                    "steps": [
                        {
                            "instruction": "步行400米",
                            "distance": "400",
                            "polyline": "113.261015,23.137823;113.265000,23.140000",
                        }
                    ],
                },
                "bus": {"buslines": []},
                "taxi": [],
            },
            {
                "walking": [],
                "bus": {
                    "buslines": [
                        {
                            "name": "地铁1号线",
                            "type": "地铁线路",
                            "distance": "5000",
                            "duration": "800",
                            "departure_stop": "Metro A",
                            "arrival_stop": "Metro B",
                            "via_num": "5",
                            "polyline": "113.265000,23.140000;113.290000,23.120000",
                        }
                    ]
                },
                "taxi": [],
            },
            {
                "walking": {
                    "distance": "300",
                    "duration": "300",
                    "steps": [
                        {
                            "instruction": "步行300米",
                            "distance": "300",
                            "polyline": "113.290000,23.120000;113.295000,23.118000",
                        }
                    ],
                },
                "bus": {"buslines": []},
                "taxi": [],
            },
            {
                "walking": [],
                "bus": {
                    "buslines": [
                        {
                            "name": "B2",
                            "type": "普通公交线路",
                            "distance": "4800",
                            "duration": "500",
                            "departure_stop": "Stop C",
                            "arrival_stop": "Stop D",
                            "via_num": "4",
                            "polyline": "113.295000,23.118000;113.319263,23.109078",
                        }
                    ]
                },
                "taxi": [],
            },
            {
                "walking": {
                    "distance": "254",
                    "duration": "250",
                    "steps": [
                        {
                            "instruction": "步行254米",
                            "distance": "254",
                            "polyline": "113.319263,23.109078",
                        }
                    ],
                },
                "bus": {"buslines": []},
                "taxi": [],
            },
        ],
    )


def run_amap_transit(
    provider: Any,
    handler: Any,
    *,
    cache: Any = None,
) -> Any:
    async def run_scenario() -> Any:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            amap = provider.AmapTransitProvider(
                api_key="local-secret-key",
                http_client=client,
                cache=cache,
            )
            return await amap.get_route(transit_request(provider))

    return asyncio.run(run_scenario())


def test_amap_transit_request_sends_city_and_time_parameters() -> None:
    provider = load_transit_provider_module()
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=amap_transit_response())

    result = run_amap_transit(provider, handle)

    assert isinstance(result, provider.ProviderSuccess)
    assert requests[0].url.path == "/v3/direction/transit/integrated"
    params = requests[0].url.params
    assert params["key"] == "local-secret-key"
    assert params["origin"] == "113.261015,23.137823"
    assert params["destination"] == "113.319263,23.109078"
    assert params["city"] == "广州"
    assert params["strategy"] == "0"
    assert params["nightflag"] == "0"
    assert params["date"] == "2026-08-01"
    assert params["time"] == "09:15"
    assert params["extensions"] == "base"
    assert params["output"] == "JSON"
    assert "origin_id" not in params
    assert "destination_id" not in params


def test_amap_transit_parses_walking_and_bus_steps_into_one_plan() -> None:
    provider = load_transit_provider_module()

    result = run_amap_transit(
        provider,
        lambda _: httpx.Response(200, json=amap_transit_response()),
    )

    assert isinstance(result, provider.ProviderSuccess)
    assert result.provider == "AMAP"
    assert result.cached is False
    assert result.estimated is False
    assert result.data.mode == "TRANSIT"
    assert result.data.distance_meters == 6085
    assert result.data.duration_seconds == 1250
    assert result.data.walking_distance_meters == 654
    assert result.data.transfer_count == 0
    assert [step.distance_meters for step in result.data.steps] == [400, 3431, 2254]
    assert [(point.longitude, point.latitude) for point in result.data.polyline] == [
        (113.261015, 23.137823),
        (113.27, 23.13),
        (113.319263, 23.109078),
    ]


def test_amap_transit_keeps_walking_and_bus_geometry_from_the_same_segment() -> None:
    provider = load_transit_provider_module()
    payload = amap_transit_response()
    path = payload["route"]["transits"][0]
    path["segments"] = [
        {
            "walking": {
                "distance": "120",
                "duration": "100",
                "steps": [
                    {
                        "instruction": "步行至车站",
                        "distance": "120",
                        "polyline": "113.261015,23.137823;113.270000,23.130000",
                    }
                ],
            },
            "bus": {
                "buslines": [
                    {
                        "name": "B1",
                        "type": "普通公交线路",
                        "distance": "3431",
                        "duration": "600",
                        "departure_stop": "Stop A",
                        "arrival_stop": "Stop B",
                        "via_num": "3",
                        "polyline": "113.270000,23.130000;113.319263,23.109078",
                    }
                ]
            },
            "taxi": [],
        }
    ]

    result = run_amap_transit(provider, lambda _: httpx.Response(200, json=payload))

    assert isinstance(result, provider.ProviderSuccess)
    assert [step.distance_meters for step in result.data.steps] == [120, 3431]
    assert [(point.longitude, point.latitude) for point in result.data.polyline] == [
        (113.261015, 23.137823),
        (113.27, 23.13),
        (113.319263, 23.109078),
    ]


def test_amap_transit_skips_segments_with_missing_geometry_but_keeps_path_facts() -> None:
    provider = load_transit_provider_module()
    payload = amap_transit_response()
    path = payload["route"]["transits"][0]
    path["segments"][0]["walking"]["steps"][0]["polyline"] = ""

    result = run_amap_transit(provider, lambda _: httpx.Response(200, json=payload))

    assert isinstance(result, provider.ProviderSuccess)
    assert result.data.distance_meters == 6085
    assert result.data.duration_seconds == 1250
    assert result.data.walking_distance_meters == 654
    assert result.data.transfer_count == 0
    assert [step.distance_meters for step in result.data.steps] == [3431, 2254]
    assert [(point.longitude, point.latitude) for point in result.data.polyline] == [
        (113.27, 23.13),
        (113.319263, 23.109078),
    ]


def test_amap_transit_uses_request_endpoints_when_all_segment_geometry_is_missing() -> None:
    provider = load_transit_provider_module()
    payload = amap_transit_response()
    path = payload["route"]["transits"][0]
    for segment in path["segments"]:
        walking = segment["walking"]
        if isinstance(walking, dict):
            for step in walking["steps"]:
                step["polyline"] = ""
        for busline in segment["bus"]["buslines"]:
            busline["polyline"] = ""

    result = run_amap_transit(provider, lambda _: httpx.Response(200, json=payload))

    assert isinstance(result, provider.ProviderSuccess)
    assert result.data.distance_meters == 6085
    assert result.data.duration_seconds == 1250
    assert result.data.walking_distance_meters == 654
    assert result.data.transfer_count == 0
    assert len(result.data.steps) == 1
    assert result.data.steps[0].distance_meters == 6085
    assert result.data.steps[0].duration_seconds == 1250
    assert [(point.longitude, point.latitude) for point in result.data.steps[0].polyline] == [
        (113.261015, 23.137823),
        (113.319263, 23.109078),
    ]
    assert result.data.polyline == result.data.steps[0].polyline


def test_amap_transit_selects_the_first_candidate_when_multiple_exist() -> None:
    provider = load_transit_provider_module()
    payload = amap_transit_response()
    payload["count"] = "2"
    payload["route"]["transits"].append(
        amap_transit_response(
            walking_distance="999", distance="7000", duration="1500"
        )["route"]["transits"][0]
    )

    result = run_amap_transit(provider, lambda _: httpx.Response(200, json=payload))

    assert isinstance(result, provider.ProviderSuccess)
    assert result.data.distance_meters == 6085
    assert result.data.walking_distance_meters == 654


def test_amap_transit_counts_vehicle_transfers() -> None:
    provider = load_transit_provider_module()

    result = run_amap_transit(
        provider,
        lambda _: httpx.Response(200, json=metro_bus_transfer_fixture()),
    )

    assert isinstance(result, provider.ProviderSuccess)
    assert result.data.transfer_count == 1
    assert result.data.walking_distance_meters == 954
    assert result.data.distance_meters == 13000
    assert result.data.duration_seconds == 2100


def test_amap_transit_walking_distance_falls_back_to_step_sum() -> None:
    provider = load_transit_provider_module()
    payload = amap_transit_response()
    del payload["route"]["transits"][0]["walking_distance"]

    result = run_amap_transit(provider, lambda _: httpx.Response(200, json=payload))

    assert isinstance(result, provider.ProviderSuccess)
    assert result.data.walking_distance_meters == 2654


def test_amap_transit_missing_walking_distance_is_none() -> None:
    provider = load_transit_provider_module()
    payload = amap_transit_response()
    transit = payload["route"]["transits"][0]
    del transit["walking_distance"]
    transit["segments"] = [
        {
            "walking": [],
            "bus": {
                "buslines": [
                    {
                        "name": "B1",
                        "type": "普通公交线路",
                        "distance": "6085",
                        "duration": "1250",
                        "departure_stop": "Stop A",
                        "arrival_stop": "Stop B",
                        "via_num": "3",
                        "polyline": "113.261015,23.137823;113.319263,23.109078",
                    }
                ]
            },
            "taxi": [],
        },
    ]

    result = run_amap_transit(provider, lambda _: httpx.Response(200, json=payload))

    assert isinstance(result, provider.ProviderSuccess)
    assert result.data.walking_distance_meters is None


def test_amap_transit_empty_transits_is_a_typed_not_found_failure() -> None:
    provider = load_transit_provider_module()
    payload = amap_transit_response()
    payload["route"]["transits"] = []

    result = run_amap_transit(provider, lambda _: httpx.Response(200, json=payload))

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
def test_amap_transit_business_errors_are_mapped_to_stable_failures(
    infocode: str,
    expected_code: str,
    retryable: bool,
) -> None:
    provider = load_transit_provider_module()
    payload = {
        "status": "0",
        "info": "provider rejected the request",
        "infocode": infocode,
        "count": "0",
    }

    result = run_amap_transit(provider, lambda _: httpx.Response(200, json=payload))

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
def test_amap_transit_transport_failures_are_retryable_results(
    response_factory: Any,
    expected_code: str,
) -> None:
    provider = load_transit_provider_module()

    result = run_amap_transit(provider, response_factory)

    assert isinstance(result, provider.ProviderFailure)
    assert result.error_code == expected_code
    assert result.retryable is True


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
def test_amap_transit_http_statuses_map_to_stable_failures(
    status_code: int,
    expected_code: str,
    retryable: bool,
) -> None:
    provider = load_transit_provider_module()

    result = run_amap_transit(provider, lambda _: httpx.Response(status_code))

    assert isinstance(result, provider.ProviderFailure)
    assert result.error_code == expected_code
    assert result.retryable is retryable


def invalid_transit_payload(case: str) -> dict[str, object]:
    payload = amap_transit_response()
    transit = payload["route"]["transits"][0]
    if case == "missing-route":
        del payload["route"]
    elif case == "invalid-distance":
        transit["distance"] = "not-a-number"
    elif case == "missing-step-time":
        del transit["segments"][0]["walking"]["duration"]
    elif case == "invalid-polyline":
        transit["segments"][1]["bus"]["buslines"][0]["polyline"] = "not-a-coordinate"
    elif case == "negative-duration":
        transit["duration"] = "-1"
    elif case == "long-instruction":
        transit["segments"][1]["bus"]["buslines"][0]["name"] = "x" * 301
    elif case == "out-of-range-coordinate":
        transit["segments"][1]["bus"]["buslines"][0]["polyline"] = "181,23"
    elif case == "malformed-nonempty-segment-array":
        # walking is a non-empty ARRAY — malformed; must fail closed, not be
        # silently treated as "no segment" (F6).
        transit["segments"][0]["walking"] = [{"garbage": True}]
    else:
        raise AssertionError(f"unknown invalid transit case: {case}")
    return payload


@pytest.mark.parametrize(
    "case",
    [
        "missing-route",
        "invalid-distance",
        "missing-step-time",
        "invalid-polyline",
        "negative-duration",
        "long-instruction",
        "out-of-range-coordinate",
        "malformed-nonempty-segment-array",
    ],
)
def test_amap_invalid_transit_payload_is_reported_as_a_schema_change(case: str) -> None:
    provider = load_transit_provider_module()

    result = run_amap_transit(
        provider,
        lambda _: httpx.Response(200, json=invalid_transit_payload(case)),
    )

    assert isinstance(result, provider.ProviderFailure)
    assert result.error_code == "PROVIDER_SCHEMA_CHANGED"
    assert result.retryable is True


def test_amap_transit_invalid_json_is_reported_as_a_schema_change() -> None:
    provider = load_transit_provider_module()

    result = run_amap_transit(provider, lambda _: httpx.Response(200, content=b"not-json"))

    assert isinstance(result, provider.ProviderFailure)
    assert result.error_code == "PROVIDER_SCHEMA_CHANGED"


def test_amap_transit_uses_json_cache_and_redacts_credentials() -> None:
    provider = load_transit_provider_module()
    cache = FakeJsonCache()
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=amap_transit_response())

    async def run_scenario() -> tuple[Any, Any]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            amap = provider.AmapTransitProvider(
                api_key="local-secret-key",
                http_client=client,
                cache=cache,
                cache_ttl_seconds=3600,
            )
            request = transit_request(provider)
            return await amap.get_route(request), await amap.get_route(request)

    first, cached = asyncio.run(run_scenario())

    assert isinstance(first, provider.ProviderSuccess)
    assert first.cached is False
    assert isinstance(cached, provider.ProviderSuccess)
    assert cached.cached is True
    assert cached.data == first.data
    assert len(requests) == 1
    cache_key, _, ttl_seconds = cache.writes[0]
    assert cache_key.startswith("map:transit:v1:")
    assert ttl_seconds == 3600
    assert "local-secret-key" not in cache_key
    assert "113.261015" not in cache_key


def test_amap_transit_cache_key_distinguishes_city_and_time() -> None:
    provider = load_transit_provider_module()
    request = transit_request(provider)
    same_instant = transit_request(
        provider,
        departure_at=request.departure_at.astimezone(timezone(timedelta(hours=8))),
    )
    different_city = transit_request(provider, city="深圳")
    different_time = transit_request(
        provider,
        departure_at=request.departure_at + timedelta(minutes=15),
    )
    same_bucket = transit_request(
        provider,
        departure_at=request.departure_at + timedelta(minutes=5),
    )
    different_poi = transit_request(provider, destination_poi_id="another-destination")

    base_key = provider.AmapTransitProvider._cache_key(request)

    assert provider.AmapTransitProvider._cache_key(same_instant) == base_key
    assert provider.AmapTransitProvider._cache_key(same_bucket) == base_key
    assert provider.AmapTransitProvider._cache_key(different_city) != base_key
    assert provider.AmapTransitProvider._cache_key(different_time) != base_key
    assert provider.AmapTransitProvider._cache_key(different_poi) != base_key


@pytest.mark.parametrize(
    "cache",
    [FailingJsonCache(fail_reads=True), FailingJsonCache(fail_writes=True)],
)
def test_amap_transit_cache_failures_degrade_to_a_live_response(cache: Any) -> None:
    provider = load_transit_provider_module()

    result = run_amap_transit(
        provider,
        lambda _: httpx.Response(200, json=amap_transit_response()),
        cache=cache,
    )

    assert isinstance(result, provider.ProviderSuccess)
    assert result.cached is False


def test_amap_transit_httpx_info_log_redacts_the_api_key(
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider = load_transit_provider_module()
    secret = "transit-key-that-must-not-appear"
    caplog.set_level(logging.INFO, logger="httpx")

    async def run_scenario() -> Any:
        transport = httpx.MockTransport(
            lambda _: httpx.Response(200, json=amap_transit_response())
        )
        async with httpx.AsyncClient(transport=transport) as client:
            amap = provider.AmapTransitProvider(api_key=secret, http_client=client)
            return await amap.get_route(transit_request(provider))

    result = asyncio.run(run_scenario())

    assert isinstance(result, provider.ProviderSuccess)
    assert secret not in caplog.text
    assert "REDACTED" in caplog.text


@pytest.mark.parametrize(
    ("api_key", "cache_ttl_seconds"),
    [("", 3600), ("local-key", 0), ("local-key", -1)],
)
def test_amap_transit_provider_rejects_invalid_configuration(
    api_key: str,
    cache_ttl_seconds: int,
) -> None:
    provider = load_transit_provider_module()

    with pytest.raises(ValueError):
        provider.AmapTransitProvider(
            api_key=api_key,
            http_client=object(),
            cache_ttl_seconds=cache_ttl_seconds,
        )


# ── TRANSIT cost parsing (B19-B) ─────────────────────────────────────────────


def test_amap_transit_parses_integer_string_cost() -> None:
    provider = load_transit_provider_module()

    result = run_amap_transit(
        provider,
        lambda _: httpx.Response(200, json=amap_transit_response(cost="2")),
    )

    assert isinstance(result, provider.ProviderSuccess)
    assert result.data.estimated_cost == 2.0


def test_amap_transit_parses_decimal_string_cost() -> None:
    provider = load_transit_provider_module()

    result = run_amap_transit(
        provider,
        lambda _: httpx.Response(200, json=amap_transit_response(cost="2.5")),
    )

    assert isinstance(result, provider.ProviderSuccess)
    assert result.data.estimated_cost == 2.5


@pytest.mark.parametrize("cost_value", ["", None])
def test_amap_transit_missing_or_empty_cost_is_unknown_not_free(cost_value: object) -> None:
    provider = load_transit_provider_module()

    result = run_amap_transit(
        provider,
        lambda _: httpx.Response(200, json=amap_transit_response(cost=cost_value)),
    )

    # Unknown cost must be None, never 0 (0 means free, None means unknown).
    assert isinstance(result, provider.ProviderSuccess)
    assert result.data.estimated_cost is None


def test_amap_transit_malformed_cost_is_a_schema_change_failure() -> None:
    provider = load_transit_provider_module()

    result = run_amap_transit(
        provider,
        lambda _: httpx.Response(200, json=amap_transit_response(cost="abc")),
    )

    # A malformed optional field follows the existing route-provider policy:
    # the whole response is treated as a schema change, never silently None.
    assert isinstance(result, provider.ProviderFailure)
    assert result.error_code == "PROVIDER_SCHEMA_CHANGED"
