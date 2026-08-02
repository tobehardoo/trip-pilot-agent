import asyncio
import json
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from trip_agent.domain.planning.protocols import PlanningProviderError
from trip_agent.infrastructure.amap.planning_provider import AmapPlanningProvider
from trip_agent.infrastructure.demo.planning_provider import DemoPlanningProvider
from trip_agent.providers.errors import ProviderErrorCategory, ProviderExecutionMode
from trip_agent.providers.map import Coordinates, ProviderFailure
from trip_agent.providers.route import RouteRequest
from trip_agent.worker.amqp import WorkerSettings, build_planning_provider
from trip_agent.worker.contracts import PlanningCreateCommand
from trip_agent.workflow.planner_pipeline import FallbackPlanningProvider


def _real_command() -> PlanningCreateCommand:
    fixture = Path(__file__).parent / "fixtures" / "real_provider" / "guangzhou_day_a.json"
    return PlanningCreateCommand.model_validate(
        json.loads(fixture.read_text(encoding="utf-8"))["command"]
    )


def test_legacy_demo_mode_maps_to_explicit_provider_modes() -> None:
    assert WorkerSettings(_env_file=None, demo_mode=True).resolved_provider_mode == (
        ProviderExecutionMode.DEMO_ONLY
    )
    assert WorkerSettings(
        _env_file=None,
        demo_mode=False,
        amap_web_service_key="test-key",
    ).resolved_provider_mode == ProviderExecutionMode.REAL_ONLY


def test_provider_mode_takes_precedence_but_conflicts_fail_startup() -> None:
    settings = WorkerSettings(
        _env_file=None,
        provider_mode="REAL_WITH_EXPLICIT_FALLBACK",
        amap_web_service_key="test-key",
    )
    assert settings.resolved_provider_mode == (
        ProviderExecutionMode.REAL_WITH_EXPLICIT_FALLBACK
    )

    with pytest.raises(ValidationError, match="PROVIDER_MODE conflicts with DEMO_MODE"):
        WorkerSettings(
            _env_file=None,
            provider_mode="REAL_ONLY",
            demo_mode=True,
            amap_web_service_key="test-key",
        )


def test_worker_settings_build_an_explicit_fallback_allowlist() -> None:
    settings = WorkerSettings(
        _env_file=None,
        provider_mode="REAL_WITH_EXPLICIT_FALLBACK",
        amap_web_service_key="test-key",
        provider_fallback_categories=["MALFORMED_RESPONSE"],
    )
    malformed = ProviderFailure(
        provider="AMAP",
        error_code="PROVIDER_SCHEMA_CHANGED",
        error_message="AMap returned a malformed response",
        category=ProviderErrorCategory.MALFORMED_RESPONSE,
        operation="ROUTE",
        retryable=True,
        retry_count=2,
        retry_exhausted=True,
        latency_ms=1,
        fetched_at=datetime(2026, 7, 31, tzinfo=UTC),
    )

    assert settings.provider_fallback_policy().decide(
        ProviderExecutionMode.REAL_WITH_EXPLICIT_FALLBACK,
        PlanningProviderError.from_failure(malformed).details,
    ).value == "ALLOW_FALLBACK"

    with pytest.raises(ValidationError, match="cannot be enabled for fallback"):
        WorkerSettings(
            _env_file=None,
            provider_mode="REAL_WITH_EXPLICIT_FALLBACK",
            amap_web_service_key="test-key",
            provider_fallback_categories=["AUTHENTICATION_ERROR"],
        )


def test_real_only_factory_does_not_construct_a_planning_fallback() -> None:
    settings = WorkerSettings(
        _env_file=None,
        provider_mode="REAL_ONLY",
        amap_web_service_key="test-key",
    )
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(500))
    )
    provider = build_planning_provider(settings, http_client=client)
    asyncio.run(client.aclose())

    assert isinstance(provider, AmapPlanningProvider)
    assert not isinstance(provider, FallbackPlanningProvider)
    assert provider._route_fallback is None


def test_real_only_factory_constructs_zero_demo_providers(monkeypatch: object) -> None:
    amqp = import_module("trip_agent.worker.amqp")
    calls = {"planning": 0, "route": 0}

    def planning_spy() -> object:
        calls["planning"] += 1
        raise AssertionError("REAL_ONLY must not construct DemoPlanningProvider")

    def route_spy() -> object:
        calls["route"] += 1
        raise AssertionError("REAL_ONLY must not construct DemoRouteProvider")

    monkeypatch.setattr(amqp, "DemoPlanningProvider", planning_spy)
    monkeypatch.setattr(amqp, "DemoRouteProvider", route_spy)
    settings = WorkerSettings(
        _env_file=None,
        provider_mode="REAL_ONLY",
        amap_web_service_key="test-key",
    )
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(500))
    )

    provider = amqp.build_planning_provider(settings, http_client=client)
    asyncio.run(client.aclose())

    assert isinstance(provider, AmapPlanningProvider)
    assert calls == {"planning": 0, "route": 0}


def test_demo_only_factory_needs_no_key_or_http_client() -> None:
    settings = WorkerSettings(_env_file=None, provider_mode="DEMO_ONLY")

    assert isinstance(build_planning_provider(settings), DemoPlanningProvider)


def test_real_only_route_failure_never_calls_demo_fallback() -> None:
    class FailedRoute:
        async def get_route(self, _request: object) -> ProviderFailure:
            return ProviderFailure(
                provider="AMAP",
                error_code="PROVIDER_TIMEOUT",
                error_message="AMap route request timed out",
                category=ProviderErrorCategory.TIMEOUT,
                operation="ROUTE",
                retryable=True,
                retry_count=2,
                retry_exhausted=True,
                latency_ms=1,
                fetched_at=datetime(2026, 7, 31, tzinfo=UTC),
            )

    class DemoRouteSpy:
        calls = 0

        async def get_route(self, _request: object) -> object:
            self.calls += 1
            raise AssertionError("REAL_ONLY must not call DemoRouteProvider")

    demo = DemoRouteSpy()
    provider = AmapPlanningProvider(
        object(),
        FailedRoute(),
        route_fallback=demo,
        provider_mode=ProviderExecutionMode.REAL_ONLY,
    )
    request = RouteRequest(
        origin=Coordinates(longitude=113.3, latitude=23.1),
        destination=Coordinates(longitude=113.4, latitude=23.2),
        departure_at=datetime(2026, 8, 1, tzinfo=UTC),
        mode="WALKING",
    )

    with pytest.raises(PlanningProviderError) as failure:
        asyncio.run(provider._route(request))

    assert failure.value.details.category == ProviderErrorCategory.TIMEOUT
    assert failure.value.details.fallback_attempted is False
    assert demo.calls == 0


def test_real_only_poi_failure_never_calls_demo_route() -> None:
    class FailedMap:
        async def search_pois(self, _request: object) -> ProviderFailure:
            return ProviderFailure(
                provider="AMAP",
                error_code="PROVIDER_AUTH_FAILED",
                error_message="AMap authentication failed",
                category=ProviderErrorCategory.AUTHENTICATION_ERROR,
                operation="POI_SEARCH",
                retryable=False,
                safe_provider_code="10001",
                latency_ms=1,
                fetched_at=datetime(2026, 7, 31, tzinfo=UTC),
            )

    class DemoRouteSpy:
        calls = 0

        async def get_route(self, _request: object) -> object:
            self.calls += 1
            raise AssertionError("REAL_ONLY must not call DemoRouteProvider")

    demo = DemoRouteSpy()
    provider = AmapPlanningProvider(
        FailedMap(),
        object(),
        route_fallback=demo,
        provider_mode=ProviderExecutionMode.REAL_ONLY,
    )

    with pytest.raises(PlanningProviderError) as failure:
        asyncio.run(provider.plan(_real_command()))

    assert failure.value.details.category == ProviderErrorCategory.AUTHENTICATION_ERROR
    assert failure.value.details.safe_provider_code == "10001"
    assert demo.calls == 0


def test_real_only_internal_provider_exception_never_calls_demo_route() -> None:
    class BrokenMap:
        async def search_pois(self, _request: object) -> object:
            raise TypeError("adapter implementation defect")

    class DemoRouteSpy:
        calls = 0

        async def get_route(self, _request: object) -> object:
            self.calls += 1
            raise AssertionError("REAL_ONLY must not call DemoRouteProvider")

    demo = DemoRouteSpy()
    provider = AmapPlanningProvider(
        BrokenMap(),
        object(),
        route_fallback=demo,
        provider_mode=ProviderExecutionMode.REAL_ONLY,
    )

    with pytest.raises(TypeError, match="adapter implementation defect"):
        asyncio.run(provider.plan(_real_command()))

    assert demo.calls == 0
