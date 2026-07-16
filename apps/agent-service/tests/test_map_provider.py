import asyncio
import logging
from datetime import UTC, datetime
from importlib import import_module
from importlib.util import find_spec
from typing import Any

import httpx
import pytest
from pydantic import ValidationError


def load_map_provider_module():
    assert find_spec("trip_agent.providers") is not None, "map provider package is missing"
    return import_module("trip_agent.providers.map")


def make_amap_poi(**overrides: object) -> dict[str, object]:
    poi: dict[str, object] = {
        "id": "demo-poi",
        "name": "Museum",
        "location": "113.319263,23.109078",
        "type": "Culture;Museum",
        "typecode": "140100",
        "pname": "Guangdong",
        "cityname": "Guangzhou",
        "adname": "Tianhe",
        "address": "2 Zhujiang East Road",
    }
    poi.update(overrides)
    return poi


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


def test_provider_models_validate_requests_and_represent_sourced_pois() -> None:
    provider = load_map_provider_module()

    request = provider.PoiSearchRequest(city=" 广州 ", keyword=" 博物馆 ", limit=10)
    poi = provider.Poi(
        provider_id="B00140TWHT",
        name="广东省博物馆",
        coordinates=provider.Coordinates(longitude=113.319263, latitude=23.109078),
        type_name="科教文化服务;博物馆;博物馆",
        type_code="140100",
        province="广东省",
        city="广州市",
        district="天河区",
        address="珠江东路2号",
    )
    result = provider.ProviderSuccess(
        data=(poi,),
        provider="AMAP",
        latency_ms=12,
        cached=False,
        fetched_at=datetime(2026, 7, 16, tzinfo=UTC),
        estimated=False,
    )

    assert request.city == "广州"
    assert request.keyword == "博物馆"
    assert result.data[0].provider_id == "B00140TWHT"
    assert result.estimated is False


@pytest.mark.parametrize(
    ("field", "value"),
    [("city", ""), ("keyword", "x" * 81), ("limit", 26)],
)
def test_poi_search_request_rejects_values_outside_amap_limits(field: str, value: object) -> None:
    provider = load_map_provider_module()
    values = {"city": "广州", "keyword": "博物馆", "limit": 10, field: value}

    with pytest.raises(ValidationError):
        provider.PoiSearchRequest(**values)


def test_amap_text_search_parses_and_caches_successful_pois() -> None:
    provider = load_map_provider_module()
    cache = FakeJsonCache()
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "status": "1",
                "info": "OK",
                "infocode": "10000",
                "count": "1",
                "pois": [
                    {
                        "id": "B00140TWHT",
                        "name": "广东省博物馆",
                        "location": "113.319263,23.109078",
                        "type": "科教文化服务;博物馆;博物馆",
                        "typecode": "140100",
                        "pname": "广东省",
                        "cityname": "广州市",
                        "adname": "天河区",
                        "address": "珠江东路2号",
                    }
                ],
            },
        )

    async def run_scenario() -> tuple[Any, Any]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            amap = provider.AmapMapProvider(
                api_key="local-secret-key",
                http_client=client,
                cache=cache,
                cache_ttl_seconds=3600,
            )
            search = provider.PoiSearchRequest(city="广州", keyword="博物馆", limit=10)
            return await amap.search_pois(search), await amap.search_pois(search)

    first, cached = asyncio.run(run_scenario())

    assert isinstance(first, provider.ProviderSuccess)
    assert first.cached is False
    assert first.provider == "AMAP"
    assert first.data[0].name == "广东省博物馆"
    assert first.data[0].coordinates.longitude == pytest.approx(113.319263)
    assert isinstance(cached, provider.ProviderSuccess)
    assert cached.cached is True
    assert cached.data == first.data
    assert len(requests) == 1
    assert requests[0].url.path == "/v5/place/text"
    assert requests[0].url.params["keywords"] == "博物馆"
    assert requests[0].url.params["region"] == "广州"
    assert requests[0].url.params["city_limit"] == "true"
    assert requests[0].url.params["page_size"] == "10"
    assert requests[0].url.params["key"] == "local-secret-key"
    cache_key, _, ttl_seconds = cache.writes[0]
    assert ttl_seconds == 3600
    assert "local-secret-key" not in cache_key
    assert "广州" not in cache_key
    assert "博物馆" not in cache_key


@pytest.mark.parametrize(
    ("infocode", "expected_code", "retryable"),
    [
        ("10001", "PROVIDER_AUTH_FAILED", False),
        ("10004", "PROVIDER_RATE_LIMITED", True),
        ("10020", "PROVIDER_RATE_LIMITED", True),
        ("10003", "PROVIDER_QUOTA_EXHAUSTED", False),
        ("10010", "PROVIDER_QUOTA_EXHAUSTED", False),
        ("10044", "PROVIDER_QUOTA_EXHAUSTED", False),
        ("10017", "PROVIDER_UNAVAILABLE", True),
        ("20000", "PROVIDER_REQUEST_INVALID", False),
        ("20003", "PROVIDER_ERROR", False),
        ("30000", "PROVIDER_UNAVAILABLE", True),
    ],
)
def test_amap_business_errors_are_mapped_to_stable_failures(
    infocode: str,
    expected_code: str,
    retryable: bool,
) -> None:
    provider = load_map_provider_module()

    def handle(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "0",
                "info": "provider rejected the request",
                "infocode": infocode,
                "pois": [],
            },
        )

    async def run_scenario() -> Any:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            amap = provider.AmapMapProvider(api_key="local-secret-key", http_client=client)
            return await amap.search_pois(
                provider.PoiSearchRequest(city="Guangzhou", keyword="museum")
            )

    result = asyncio.run(run_scenario())

    assert isinstance(result, provider.ProviderFailure)
    assert result.error_code == expected_code
    assert result.retryable is retryable
    assert "local-secret-key" not in result.error_message


def test_amap_empty_result_is_a_typed_not_found_failure() -> None:
    provider = load_map_provider_module()

    def handle(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"status": "1", "info": "OK", "infocode": "10000", "pois": []},
        )

    async def run_scenario() -> Any:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            amap = provider.AmapMapProvider(api_key="local-secret-key", http_client=client)
            return await amap.search_pois(
                provider.PoiSearchRequest(city="Guangzhou", keyword="missing-place")
            )

    result = asyncio.run(run_scenario())

    assert isinstance(result, provider.ProviderFailure)
    assert result.error_code == "POI_NOT_FOUND"
    assert result.retryable is False


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
def test_amap_transport_failures_are_returned_as_retryable_results(
    response_factory: Any,
    expected_code: str,
) -> None:
    provider = load_map_provider_module()

    async def run_scenario() -> Any:
        async with httpx.AsyncClient(transport=httpx.MockTransport(response_factory)) as client:
            amap = provider.AmapMapProvider(api_key="local-secret-key", http_client=client)
            return await amap.search_pois(
                provider.PoiSearchRequest(city="Guangzhou", keyword="museum")
            )

    result = asyncio.run(run_scenario())

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
def test_amap_http_statuses_are_mapped_without_leaking_httpx_exceptions(
    status_code: int,
    expected_code: str,
    retryable: bool,
) -> None:
    provider = load_map_provider_module()

    async def run_scenario() -> Any:
        transport = httpx.MockTransport(lambda _: httpx.Response(status_code))
        async with httpx.AsyncClient(transport=transport) as client:
            amap = provider.AmapMapProvider(api_key="local-secret-key", http_client=client)
            return await amap.search_pois(
                provider.PoiSearchRequest(city="Guangzhou", keyword="museum")
            )

    result = asyncio.run(run_scenario())

    assert isinstance(result, provider.ProviderFailure)
    assert result.error_code == expected_code
    assert result.retryable is retryable


def test_amap_invalid_poi_coordinates_are_reported_as_schema_changes() -> None:
    provider = load_map_provider_module()

    def handle(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "1",
                "info": "OK",
                "infocode": "10000",
                "pois": [make_amap_poi(location="not-a-coordinate")],
            },
        )

    async def run_scenario() -> Any:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            amap = provider.AmapMapProvider(api_key="local-secret-key", http_client=client)
            return await amap.search_pois(
                provider.PoiSearchRequest(city="Guangzhou", keyword="museum")
            )

    result = asyncio.run(run_scenario())

    assert isinstance(result, provider.ProviderFailure)
    assert result.error_code == "PROVIDER_SCHEMA_CHANGED"
    assert result.retryable is False


@pytest.mark.parametrize("missing_field", ["pois", "typecode", "address"])
def test_amap_success_missing_required_fields_is_reported_as_a_schema_change(
    missing_field: str,
) -> None:
    provider = load_map_provider_module()
    payload: dict[str, object] = {
        "status": "1",
        "info": "OK",
        "infocode": "10000",
        "pois": [make_amap_poi()],
    }
    if missing_field == "pois":
        del payload["pois"]
    else:
        poi = make_amap_poi()
        del poi[missing_field]
        payload["pois"] = [poi]

    def handle(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    async def run_scenario() -> Any:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            amap = provider.AmapMapProvider(api_key="local-secret-key", http_client=client)
            return await amap.search_pois(
                provider.PoiSearchRequest(city="Guangzhou", keyword="museum")
            )

    result = asyncio.run(run_scenario())

    assert isinstance(result, provider.ProviderFailure)
    assert result.error_code == "PROVIDER_SCHEMA_CHANGED"


def test_amap_invalid_json_is_reported_as_a_schema_change() -> None:
    provider = load_map_provider_module()

    def handle(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not-json")

    async def run_scenario() -> Any:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            amap = provider.AmapMapProvider(api_key="local-secret-key", http_client=client)
            return await amap.search_pois(
                provider.PoiSearchRequest(city="Guangzhou", keyword="museum")
            )

    result = asyncio.run(run_scenario())

    assert isinstance(result, provider.ProviderFailure)
    assert result.error_code == "PROVIDER_SCHEMA_CHANGED"


def test_amap_httpx_info_log_redacts_the_api_key(caplog: pytest.LogCaptureFixture) -> None:
    provider = load_map_provider_module()
    secret = "should-never-appear-in-logs"
    caplog.set_level(logging.INFO, logger="httpx")

    def handle(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "1",
                "info": "OK",
                "infocode": "10000",
                "pois": [make_amap_poi()],
            },
        )

    async def run_scenario() -> Any:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            amap = provider.AmapMapProvider(api_key=secret, http_client=client)
            return await amap.search_pois(
                provider.PoiSearchRequest(city="Guangzhou", keyword="museum")
            )

    result = asyncio.run(run_scenario())

    assert isinstance(result, provider.ProviderSuccess)
    assert secret not in caplog.text
    assert "REDACTED" in caplog.text


@pytest.mark.parametrize(
    "cache",
    [FailingJsonCache(fail_reads=True), FailingJsonCache(fail_writes=True)],
)
def test_amap_cache_failures_degrade_to_a_live_provider_response(cache: Any) -> None:
    provider = load_map_provider_module()

    def handle(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "1",
                "info": "OK",
                "infocode": "10000",
                "pois": [make_amap_poi()],
            },
        )

    async def run_scenario() -> Any:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            amap = provider.AmapMapProvider(
                api_key="local-secret-key",
                http_client=client,
                cache=cache,
            )
            return await amap.search_pois(
                provider.PoiSearchRequest(city="Guangzhou", keyword="museum")
            )

    result = asyncio.run(run_scenario())

    assert isinstance(result, provider.ProviderSuccess)
    assert result.cached is False


def test_amap_corrupt_cache_entry_is_replaced_from_the_live_provider() -> None:
    provider = load_map_provider_module()
    cache = FakeJsonCache()
    cache.values["map:poi:v1:placeholder"] = "not-json"
    calls = 0

    def handle(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={
                "status": "1",
                "info": "OK",
                "infocode": "10000",
                "pois": [make_amap_poi()],
            },
        )

    async def run_scenario() -> Any:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            amap = provider.AmapMapProvider(
                api_key="local-secret-key",
                http_client=client,
                cache=cache,
            )
            request = provider.PoiSearchRequest(city="Guangzhou", keyword="museum")
            cache_key = amap._cache_key(request)
            cache.values[cache_key] = "not-json"
            return await amap.search_pois(request)

    result = asyncio.run(run_scenario())

    assert isinstance(result, provider.ProviderSuccess)
    assert calls == 1
    assert cache.writes


def test_amap_cache_key_uses_unambiguous_structured_input() -> None:
    provider = load_map_provider_module()
    first = provider.PoiSearchRequest(city="a\0b", keyword="c")
    second = provider.PoiSearchRequest(city="a", keyword="b\0c")

    assert provider.AmapMapProvider._cache_key(first) != provider.AmapMapProvider._cache_key(second)


def test_demo_map_provider_returns_deterministic_estimated_pois() -> None:
    provider = load_map_provider_module()
    request = provider.PoiSearchRequest(city="Guangzhou", keyword="museum", limit=3)

    first = asyncio.run(provider.DemoMapProvider().search_pois(request))
    second = asyncio.run(provider.DemoMapProvider().search_pois(request))

    assert isinstance(first, provider.ProviderSuccess)
    assert first.provider == "DEMO"
    assert first.estimated is True
    assert first.data == second.data
    assert len(first.data) == 1
    assert first.data[0].city == "Guangzhou"
