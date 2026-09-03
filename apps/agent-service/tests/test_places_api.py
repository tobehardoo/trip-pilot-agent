"""B13-D — protected agent-api place search endpoint.

The endpoint is internal-only (X-Internal-Token), never exposes provider
keys, and flags Demo candidates as estimated — candidates are never
verification evidence.

B13_FIX.1 R4: the provider/client are owned by the FastAPI lifespan and
injected through a typed dependency; tests use ``app.dependency_overrides``
(no module-level mutable provider state).
"""

from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

import trip_agent.places.api as places_api
from trip_agent.main import app
from trip_agent.providers.map import (
    Coordinates,
    DemoMapProvider,
    Poi,
    ProviderSuccess,
)


def _client(token: str = "test-internal-token"):
    return TestClient(app)


def _search(city: str = "广州", keyword: str = "陈家祠", limit: int = 10):
    return {"city": city, "keyword": keyword, "limit": limit}


def _headers(token: str = "test-internal-token"):
    return {"X-Internal-Token": token}


def _override_demo() -> None:
    """Route the dependency to a fresh DemoMapProvider for this test."""
    app.dependency_overrides[places_api.get_place_search_provider] = lambda: DemoMapProvider()


def test_search_requires_internal_token(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_INTERNAL_TOKEN", "test-internal-token")
    _override_demo()
    response = _client().post("/internal/v1/places/search", json=_search())
    app.dependency_overrides.clear()
    assert response.status_code == 401


def test_search_rejects_wrong_token(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_INTERNAL_TOKEN", "test-internal-token")
    _override_demo()
    response = _client().post(
        "/internal/v1/places/search",
        json=_search(),
        headers=_headers("wrong"),
    )
    app.dependency_overrides.clear()
    assert response.status_code == 401


def test_search_returns_demo_candidates_flagged_estimated(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_INTERNAL_TOKEN", "test-internal-token")
    _override_demo()
    response = _client().post(
        "/internal/v1/places/search",
        json=_search(),
        headers=_headers(),
    )
    app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "DEMO"
    assert body["estimated"] is True
    assert len(body["candidates"]) >= 1
    candidate = body["candidates"][0]
    # The full structured shape must round-trip for PlaceRef persistence.
    assert set(candidate) == {
        "provider",
        "providerPoiId",
        "name",
        "address",
        "province",
        "city",
        "district",
        "longitude",
        "latitude",
        "estimated",
    }
    assert candidate["provider"] == "DEMO"
    assert candidate["providerPoiId"].startswith("demo-")
    assert candidate["name"] == "陈家祠 (demo)"
    assert candidate["estimated"] is True
    # Candidates are never verification evidence.
    assert "verified" not in body
    assert "verification" not in body


def test_search_respects_limit_bounds(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_INTERNAL_TOKEN", "test-internal-token")
    _override_demo()
    for limit in (0, 26):
        response = _client().post(
            "/internal/v1/places/search", json=_search(limit=limit), headers=_headers()
        )
        assert response.status_code == 422
    response = _client().post(
        "/internal/v1/places/search", json=_search(limit=25), headers=_headers()
    )
    app.dependency_overrides.clear()
    assert response.status_code == 200


def test_search_rejects_blank_keyword_and_city(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_INTERNAL_TOKEN", "test-internal-token")
    _override_demo()
    for payload in (_search(keyword=""), _search(city="")):
        response = _client().post("/internal/v1/places/search", json=payload, headers=_headers())
        assert response.status_code == 422
    app.dependency_overrides.clear()


def test_provider_failure_maps_to_safe_502(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_INTERNAL_TOKEN", "test-internal-token")

    class _BrokenProvider:
        async def search_pois(self, request):
            from trip_agent.providers.map import ProviderFailure

            return ProviderFailure(
                provider="AMAP",
                error_code="PROVIDER_QUOTA_EXHAUSTED",
                error_message="raw upstream secret detail",
                category="QUOTA_EXCEEDED",
                operation="PLANNING",
                retryable=False,
                latency_ms=1,
                fetched_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
            )

    app.dependency_overrides[places_api.get_place_search_provider] = lambda: _BrokenProvider()
    try:
        response = _client().post(
            "/internal/v1/places/search",
            json=_search(),
            headers=_headers(),
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 502
    # The raw upstream message must never leak to the client.
    assert "secret" not in response.text
    assert "PROVIDER_QUOTA_EXHAUSTED" in response.text


# ── B13_FIX.1 R4: lifespan-owned runtime and client lifecycle ───────────────


def test_missing_runtime_fails_closed(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_INTERNAL_TOKEN", "test-internal-token")

    bare = FastAPI()
    bare.include_router(places_api.router)
    # No lifespan set: app.state.place_search_runtime is absent.
    with TestClient(bare) as client:
        response = client.post(
            "/internal/v1/places/search",
            json=_search(),
            headers=_headers(),
        )
    assert response.status_code == 503


def test_demo_runtime_never_opens_an_http_client(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_INTERNAL_TOKEN", "test-internal-token")
    monkeypatch.setenv("PROVIDER_MODE", "DEMO_ONLY")
    runtime = places_api.create_place_search_runtime()
    assert runtime.client is None
    assert isinstance(runtime.provider, DemoMapProvider)


def test_real_runtime_opens_a_client_and_close_closes_it(monkeypatch) -> None:
    import asyncio

    import httpx

    monkeypatch.setenv("AGENT_INTERNAL_TOKEN", "test-internal-token")
    monkeypatch.setenv("PROVIDER_MODE", "REAL_ONLY")
    monkeypatch.setenv("AMAP_WEB_SERVICE_KEY", "test-key")
    runtime = places_api.create_place_search_runtime()
    assert runtime.client is not None
    assert isinstance(runtime.client, httpx.AsyncClient)
    assert not runtime.client.is_closed

    asyncio.run(places_api.close_place_search_runtime(runtime))
    assert runtime.client.is_closed


def test_dependency_override_is_independent_of_lifespan(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_INTERNAL_TOKEN", "test-internal-token")
    _override_demo()
    with TestClient(app) as client:
        response = client.post(
            "/internal/v1/places/search",
            json=_search(),
            headers=_headers(),
        )
    app.dependency_overrides.clear()
    assert response.status_code == 200


def test_repeated_startup_shutdown_does_not_leak(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_INTERNAL_TOKEN", "test-internal-token")
    monkeypatch.setenv("PROVIDER_MODE", "DEMO_ONLY")
    for _ in range(3):
        with TestClient(app) as client:
            assert client.get("/health").status_code == 200


# ── B14_FIX R4 (D04): no-result is a legitimate business outcome ─────────────


def test_provider_no_result_maps_to_200_empty_candidates(monkeypatch) -> None:
    """A provider that finds nothing (POI_NOT_FOUND) must surface as
    200 + empty candidates ("未找到结果"), never as a 502.  Only genuine
    provider failures (timeout/quota/network/auth) stay 502.
    """
    monkeypatch.setenv("AGENT_INTERNAL_TOKEN", "test-internal-token")

    class _NoResultProvider:
        async def search_pois(self, request):
            from trip_agent.providers.map import ProviderFailure

            return ProviderFailure(
                provider="AMAP",
                error_code="POI_NOT_FOUND",
                error_message="No matching POIs were found",
                category="NO_RESULT",
                operation="POI_SEARCH",
                retryable=False,
                latency_ms=1,
                fetched_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
            )

    app.dependency_overrides[places_api.get_place_search_provider] = lambda: _NoResultProvider()
    try:
        response = _client().post(
            "/internal/v1/places/search",
            json=_search(keyword="asdfghjklqwerty"),
            headers=_headers(),
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "AMAP"
    assert body["estimated"] is False
    assert body["candidates"] == []


def test_same_name_infrastructure_is_filtered_out_of_the_picker(monkeypatch) -> None:
    """AMap text search mixes metro stations / gates with the real place; the
    picker must never offer infrastructure entries (planning fail-closed dead
    ends), even when they share the exact keyword name with an attraction.
    """
    monkeypatch.setenv("AGENT_INTERNAL_TOKEN", "test-internal-token")

    def poi(provider_id: str, name: str, type_code: str) -> Poi:
        return Poi(
            provider_id=provider_id,
            name=name,
            coordinates=Coordinates(longitude=113.27, latitude=23.13),
            type_name="交通设施服务" if type_code.startswith("15") else "风景名胜",
            type_code=type_code,
            province="广东省",
            city="广州市",
            district="荔湾区",
            address=f"{name}地址",
        )

    class _MixedProvider:
        async def search_pois(self, request):
            return ProviderSuccess(
                data=(
                    poi("metro", "陈家祠(地铁站)", "150500"),
                    poi("attraction", "陈家祠", "110202"),
                    poi("gate", "陈家祠-南门", "150202"),
                ),
                provider="AMAP",
                latency_ms=1,
                cached=False,
                fetched_at=datetime(2026, 8, 17, tzinfo=UTC),
                estimated=False,
            )

    app.dependency_overrides[places_api.get_place_search_provider] = lambda: _MixedProvider()
    try:
        response = _client().post(
            "/internal/v1/places/search",
            json=_search(keyword="陈家祠"),
            headers=_headers(),
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert [candidate["providerPoiId"] for candidate in response.json()["candidates"]] == [
        "attraction",
    ]


def test_geo_hotspot_is_not_offered_instead_of_the_real_attraction(monkeypatch) -> None:
    """R3 regression: ``陈家祠`` resolves to the AMap geo hot-spot 190700
    ("地名地址信息·热点地名", classified OTHER) whose exact name wins the old
    ordering — the actual museum ``陈家祠堂`` (110202) must be the picker's
    first schedulable candidate instead.
    """
    monkeypatch.setenv("AGENT_INTERNAL_TOKEN", "test-internal-token")

    def poi(provider_id: str, name: str, type_code: str) -> Poi:
        return Poi(
            provider_id=provider_id,
            name=name,
            coordinates=Coordinates(longitude=113.25, latitude=23.13),
            type_name="地名地址信息" if type_code == "190700" else "风景名胜",
            type_code=type_code,
            province="广东省",
            city="广州市",
            district="荔湾区",
            address=f"{name}地址",
        )

    class _RealWorldProvider:
        async def search_pois(self, request):
            return ProviderSuccess(
                data=(
                    poi("hotspot", "陈家祠", "190700"),
                    poi("museum", "陈家祠堂", "110202"),
                    poi("square", "陈家祠广场", "110105"),
                ),
                provider="AMAP",
                latency_ms=1,
                cached=False,
                fetched_at=datetime(2026, 9, 3, tzinfo=UTC),
                estimated=False,
            )

    app.dependency_overrides[places_api.get_place_search_provider] = lambda: _RealWorldProvider()
    try:
        response = _client().post(
            "/internal/v1/places/search",
            json=_search(keyword="陈家祠"),
            headers=_headers(),
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert [candidate["providerPoiId"] for candidate in response.json()["candidates"]] == [
        "museum",
        "square",
    ]


def test_legit_non_attraction_kinds_stay_selectable(monkeypatch) -> None:
    """Dining, hotels, shopping and transport hubs remain pickable — the
    filter excludes ONLY never-schedulable kinds (OTHER/UNKNOWN/TRANSIT_INFRA).
    """
    monkeypatch.setenv("AGENT_INTERNAL_TOKEN", "test-internal-token")

    def poi(provider_id: str, name: str, type_code: str) -> Poi:
        return Poi(
            provider_id=provider_id,
            name=name,
            coordinates=Coordinates(longitude=113.30, latitude=23.12),
            type_name="place",
            type_code=type_code,
            province="广东省",
            city="广州市",
            district="越秀区",
            address=f"{name}地址",
        )

    class _KindsProvider:
        async def search_pois(self, request):
            return ProviderSuccess(
                data=(
                    poi("hotel", "白天鹅宾馆", "100100"),
                    poi("restaurant", "陶陶居", "050100"),
                    poi("mall", "正佳广场", "060100"),
                    poi("station", "广州南站", "150200"),
                    poi("hotspot", "陶陶居(热点)", "190700"),
                ),
                provider="AMAP",
                latency_ms=1,
                cached=False,
                fetched_at=datetime(2026, 9, 3, tzinfo=UTC),
                estimated=False,
            )

    app.dependency_overrides[places_api.get_place_search_provider] = lambda: _KindsProvider()
    try:
        response = _client().post(
            "/internal/v1/places/search",
            json=_search(keyword="陶陶居"),
            headers=_headers(),
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    ids = [candidate["providerPoiId"] for candidate in response.json()["candidates"]]
    assert "hotspot" not in ids
    for kept in ("hotel", "restaurant", "mall", "station"):
        assert kept in ids

