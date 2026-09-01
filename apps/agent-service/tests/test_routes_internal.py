from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from trip_agent.main import app
from trip_agent.providers.errors import ProviderErrorCategory, ProviderOperation
from trip_agent.providers.map import ProviderFailure, ProviderSuccess
from trip_agent.providers.route import RoutePlan, RouteRequest, RouteStep
from trip_agent.routes.api import get_route_service
from trip_agent.routes.service import RouteService


def _success(request: RouteRequest, *, duration: int, distance: int = 2_000):
    polyline = (request.origin, request.destination)
    return ProviderSuccess(
        data=RoutePlan(
            mode=request.mode,
            distance_meters=distance,
            duration_seconds=duration,
            steps=(
                RouteStep(
                    instruction=f"Use {request.mode}",
                    distance_meters=distance,
                    duration_seconds=duration,
                    polyline=polyline,
                ),
            ),
            polyline=polyline,
            estimated_cost=3 if request.mode == "TRANSIT" else None,
            walking_distance_meters=300 if request.mode == "TRANSIT" else None,
            transfer_count=1 if request.mode == "TRANSIT" else None,
        ),
        provider="AMAP",
        latency_ms=7,
        cached=False,
        fetched_at=datetime(2026, 8, 20, 4, 0, tzinfo=UTC),
        estimated=False,
    )


class ScriptedProvider:
    def __init__(self, durations: dict[str, int]) -> None:
        self.durations = durations
        self.requests: list[RouteRequest] = []

    async def get_route(self, request: RouteRequest):
        self.requests.append(request)
        return _success(request, duration=self.durations[request.mode])


def _request(*, mode: str | None = None) -> dict[str, object]:
    body: dict[str, object] = {
        "origin": {"longitude": 113.31, "latitude": 23.11},
        "destination": {"longitude": 113.34, "latitude": 23.14},
        "departureAt": "2026-08-20T12:00:00+08:00",
        "city": "Guangzhou",
    }
    if mode is not None:
        body["mode"] = mode
    else:
        body["mobilityLevel"] = "STANDARD"
    return body


def test_routes_require_the_internal_service_token(monkeypatch) -> None:
    provider = ScriptedProvider({"WALKING": 600, "DRIVING": 300, "TRANSIT": 500})
    app.dependency_overrides[get_route_service] = lambda: RouteService(provider, provider)
    monkeypatch.setenv("AGENT_INTERNAL_TOKEN", "internal-secret")
    try:
        with TestClient(app) as client:
            response = client.post("/internal/v1/routes", json=_request(mode="WALKING"))
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401


def test_route_runtime_caps_the_actual_upstream_budget_to_one_attempt_per_mode(
    monkeypatch,
) -> None:
    from trip_agent.routes.api import create_route_runtime
    from trip_agent.worker.runtime import WorkerSettings

    monkeypatch.setattr("trip_agent.routes.api.httpx.AsyncClient", lambda **_kwargs: object())
    monkeypatch.setattr(
        "trip_agent.routes.api.RedisJsonCache.from_url",
        lambda *_args, **_kwargs: object(),
    )
    captured_attempts: list[int] = []

    class RecordingRetryProvider:
        def __init__(self, _delegate, policy) -> None:
            captured_attempts.append(policy.max_attempts)

    monkeypatch.setattr(
        "trip_agent.routes.api.RetryingRouteProvider",
        RecordingRetryProvider,
    )
    settings = WorkerSettings(
        provider_mode="REAL_ONLY",
        amap_web_service_key="test-key",
    )

    create_route_runtime(settings)

    assert captured_attempts == [1, 1]


def test_routes_dispatch_transit_and_return_flattened_route_facts(monkeypatch) -> None:
    road = ScriptedProvider({"WALKING": 600, "DRIVING": 300})
    transit = ScriptedProvider({"TRANSIT": 500})
    app.dependency_overrides[get_route_service] = lambda: RouteService(road, transit)
    monkeypatch.setenv("AGENT_INTERNAL_TOKEN", "internal-secret")
    try:
        with TestClient(app) as client:
            response = client.post(
                "/internal/v1/routes",
                headers={"X-Internal-Token": "internal-secret"},
                json=_request(mode="TRANSIT"),
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert road.requests == []
    assert [request.mode for request in transit.requests] == ["TRANSIT"]
    assert response.json() == {
        "mode": "TRANSIT",
        "distanceMeters": 2000,
        "durationSeconds": 500,
        "polyline": [
            {"longitude": 113.31, "latitude": 23.11},
            {"longitude": 113.34, "latitude": 23.14},
        ],
        "estimatedCost": 3.0,
        "walkingDistanceMeters": 300,
        "transferCount": 1,
        "provider": "AMAP",
        "estimated": False,
        "cached": False,
        "fetchedAt": "2026-08-20T04:00:00Z",
    }


def test_routes_reject_naive_departure_time_at_the_http_boundary(monkeypatch) -> None:
    provider = ScriptedProvider({"WALKING": 600, "DRIVING": 300, "TRANSIT": 500})
    app.dependency_overrides[get_route_service] = lambda: RouteService(provider, provider)
    monkeypatch.setenv("AGENT_INTERNAL_TOKEN", "internal-secret")
    body = _request(mode="DRIVING")
    body["departureAt"] = "2026-08-20T12:00:00"
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post(
                "/internal/v1/routes",
                headers={"X-Internal-Token": "internal-secret"},
                json=body,
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    assert provider.requests == []


def test_recommend_short_circuits_on_real_walk_facts(monkeypatch) -> None:
    # Close coordinates stay within the walking prefilter. The real 10-minute
    # WALKING route wins without probing either TRANSIT or DRIVING.
    road = ScriptedProvider({"WALKING": 600, "DRIVING": 200})
    transit = ScriptedProvider({"TRANSIT": 300})
    app.dependency_overrides[get_route_service] = lambda: RouteService(road, transit)
    monkeypatch.setenv("AGENT_INTERNAL_TOKEN", "internal-secret")
    body = _request()
    body["destination"] = {"longitude": 113.311, "latitude": 23.111}
    try:
        with TestClient(app) as client:
            response = client.post(
                "/internal/v1/routes/recommend",
                headers={"X-Internal-Token": "internal-secret"},
                json=body,
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["selectedMode"] == "WALKING"
    assert response.json()["reason"] == "WALKABLE"
    assert response.json()["providerCallsUsed"] == 1
    assert [request.mode for request in road.requests] == ["WALKING"]
    assert transit.requests == []


def test_recommend_uses_b19c_rules_and_never_compares_cost(monkeypatch) -> None:
    road = ScriptedProvider({"WALKING": 4_000, "DRIVING": 1_000})
    transit = ScriptedProvider({"TRANSIT": 1_500})
    app.dependency_overrides[get_route_service] = lambda: RouteService(road, transit)
    monkeypatch.setenv("AGENT_INTERNAL_TOKEN", "internal-secret")
    try:
        with TestClient(app) as client:
            response = client.post(
                "/internal/v1/routes/recommend",
                headers={"X-Internal-Token": "internal-secret"},
                json=_request(),
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["selectedMode"] == "DRIVING"
    assert response.json()["reason"] == "ROAD_SIGNIFICANTLY_FASTER"
    assert response.json()["providerCallsUsed"] == 2
    assert [request.mode for request in road.requests] == ["DRIVING"]
    assert [request.mode for request in transit.requests] == ["TRANSIT"]


def test_recommend_accepts_step_free_as_reduced_mobility(monkeypatch) -> None:
    road = ScriptedProvider({"WALKING": 4_000, "DRIVING": 1_000})
    transit = ScriptedProvider({"TRANSIT": 1_100})
    app.dependency_overrides[get_route_service] = lambda: RouteService(road, transit)
    monkeypatch.setenv("AGENT_INTERNAL_TOKEN", "internal-secret")
    body = _request()
    body["mobilityLevel"] = "STEP_FREE"
    try:
        with TestClient(app) as client:
            response = client.post(
                "/internal/v1/routes/recommend",
                headers={"X-Internal-Token": "internal-secret"},
                json=body,
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["providerCallsUsed"] == 2


def test_route_failure_uses_a_stable_error_without_upstream_detail(monkeypatch) -> None:
    class FailingProvider:
        async def get_route(self, _request: RouteRequest):
            return ProviderFailure(
                provider="AMAP",
                error_code="PROVIDER_RATE_LIMITED",
                error_message="secret upstream payload",
                category=ProviderErrorCategory.RATE_LIMITED,
                operation=ProviderOperation.ROUTE,
                retryable=True,
                retry_after_seconds=2,
                latency_ms=5,
                fetched_at=datetime(2026, 8, 20, 4, 0, tzinfo=UTC),
            )

    failing = FailingProvider()
    app.dependency_overrides[get_route_service] = lambda: RouteService(failing, failing)
    monkeypatch.setenv("AGENT_INTERNAL_TOKEN", "internal-secret")
    try:
        with TestClient(app) as client:
            response = client.post(
                "/internal/v1/routes",
                headers={"X-Internal-Token": "internal-secret"},
                json=_request(mode="DRIVING"),
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "2"
    assert response.json() == {
        "detail": {"code": "ROUTE_RATE_LIMITED", "retryable": True}
    }
    assert "secret upstream payload" not in response.text
