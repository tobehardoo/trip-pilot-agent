"""Tests for workflow/planner_pipeline.py and application/replan_service.py."""

import asyncio

from trip_agent.domain.planning.protocols import (
    PlanningProviderError,
    PlanningResult,
)
from trip_agent.workflow.planner_pipeline import FallbackPlanningProvider


class _MockProvider:
    """A planning provider that records calls and optionally fails."""

    def __init__(self, name: str, *, should_fail: bool = False):
        self.name = name
        self.should_fail = should_fail
        self.plan_calls = 0
        self.replan_calls = 0

    async def plan(self, _command):
        self.plan_calls += 1
        if self.should_fail:
            raise PlanningProviderError("PROVIDER_TIMEOUT")
        return PlanningResult(provider=self.name, itinerary=[])

    async def replan(self, _command):
        self.replan_calls += 1
        if self.should_fail:
            raise PlanningProviderError("PROVIDER_TIMEOUT")
        return PlanningResult(provider=self.name, itinerary=[])


class TestFallbackPlanningProvider:

    def test_plan_uses_primary_when_no_error(self):
        primary = _MockProvider("PRIMARY")
        fallback = _MockProvider("FALLBACK")
        provider = FallbackPlanningProvider(primary, fallback)

        result = asyncio.run(provider.plan(None))

        assert result.provider == "PRIMARY"
        assert primary.plan_calls == 1
        assert fallback.plan_calls == 0

    def test_plan_falls_back_on_provider_error(self):
        primary = _MockProvider("PRIMARY", should_fail=True)
        fallback = _MockProvider("FALLBACK")
        provider = FallbackPlanningProvider(primary, fallback)

        result = asyncio.run(provider.plan(None))

        assert result.provider == "FALLBACK"
        assert primary.plan_calls == 1
        assert fallback.plan_calls == 1

    def test_replan_uses_primary_when_no_error(self):
        primary = _MockProvider("PRIMARY")
        fallback = _MockProvider("FALLBACK")
        provider = FallbackPlanningProvider(primary, fallback)

        result = asyncio.run(provider.replan(None))

        assert result.provider == "PRIMARY"
        assert primary.replan_calls == 1
        assert fallback.replan_calls == 0

    def test_replan_falls_back_on_provider_error(self):
        primary = _MockProvider("PRIMARY", should_fail=True)
        fallback = _MockProvider("FALLBACK")
        provider = FallbackPlanningProvider(primary, fallback)

        result = asyncio.run(provider.replan(None))

        assert result.provider == "FALLBACK"
        assert primary.replan_calls == 1
        assert fallback.replan_calls == 1


class TestLocalReplanningProvider:

    def test_constructs_with_fallback(self):
        from trip_agent.application.replan_service import LocalReplanningProvider
        from trip_agent.providers._demo_route import DemoRouteProvider

        provider = LocalReplanningProvider(DemoRouteProvider())
        assert provider is not None
