"""Planning pipeline composition — fallback strategy.

Extracted from ``worker/processor.py``.
"""

from trip_agent.domain.planning.protocols import (
    PlanningProvider,
    PlanningProviderError,
    PlanningResult,
)
from trip_agent.worker.contracts import PlanningCreateCommand, PlanningReplanCommand


class FallbackPlanningProvider:
    """Try a primary provider; fall back to a secondary one on expected errors.

    This is used to wrap an AMap-based provider with a Demo fallback, so that
    transient map‑service failures do not block the user from seeing a plan.
    """

    def __init__(
        self, primary: PlanningProvider, fallback: PlanningProvider
    ) -> None:
        self._primary = primary
        self._fallback = fallback

    async def plan(self, command: PlanningCreateCommand) -> PlanningResult:
        try:
            return await self._primary.plan(command)
        except PlanningProviderError:
            return await self._fallback.plan(command)

    async def replan(self, command: PlanningReplanCommand) -> PlanningResult:
        try:
            return await self._primary.replan(command)
        except PlanningProviderError:
            return await self._fallback.replan(command)
