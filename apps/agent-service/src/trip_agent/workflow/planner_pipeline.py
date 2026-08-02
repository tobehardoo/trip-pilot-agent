"""Planning pipeline composition — fallback strategy.

Extracted from ``worker/processor.py``.
"""

import logging
from dataclasses import replace

from trip_agent.domain.planning.protocols import (
    PlanningProvider,
    PlanningProviderError,
    PlanningResult,
)
from trip_agent.providers.errors import (
    FallbackDecision,
    ProviderExecutionMode,
    ProviderFallbackPolicy,
)
from trip_agent.worker.contracts import (
    FallbackOperation,
    PlanningCreateCommand,
    PlanningReplanCommand,
)

logger = logging.getLogger(__name__)


class FallbackPlanningProvider:
    """Try a primary provider; fall back to a secondary one on expected errors.

    This is used to wrap an AMap-based provider with a Demo fallback, so that
    transient map‑service failures do not block the user from seeing a plan.
    """

    def __init__(
        self,
        primary: PlanningProvider,
        fallback: PlanningProvider,
        *,
        provider_mode: ProviderExecutionMode = (
            ProviderExecutionMode.REAL_WITH_EXPLICIT_FALLBACK
        ),
        fallback_policy: ProviderFallbackPolicy | None = None,
    ) -> None:
        if provider_mode != ProviderExecutionMode.REAL_WITH_EXPLICIT_FALLBACK:
            raise ValueError("FallbackPlanningProvider requires explicit fallback mode")
        self._primary = primary
        self._fallback = fallback
        self._provider_mode = provider_mode
        self._fallback_policy = fallback_policy or ProviderFallbackPolicy()

    async def plan(self, command: PlanningCreateCommand) -> PlanningResult:
        try:
            return await self._primary.plan(command)
        except PlanningProviderError as error:
            return await self._fallback_or_raise(error, command, "plan")

    async def replan(self, command: PlanningReplanCommand) -> PlanningResult:
        try:
            return await self._primary.replan(command)
        except PlanningProviderError as error:
            return await self._fallback_or_raise(error, command, "replan")

    async def _fallback_or_raise(
        self,
        error: PlanningProviderError,
        command: PlanningCreateCommand | PlanningReplanCommand | None,
        operation: str,
    ) -> PlanningResult:
        decision = self._fallback_policy.decide(self._provider_mode, error.details)
        if decision != FallbackDecision.ALLOW_FALLBACK:
            raise error.with_fallback(allowed=False, attempted=False, succeeded=False)
        logger.warning(
            "planning_provider_fallback operation=%s primary=AMAP fallback=DEMO "
            "category=%s reason=%s retry_count=%s event_id=%s trace_id=%s "
            "task_id=%s trip_id=%s",
            operation,
            error.details.category,
            error.details.error_code,
            error.details.retry_count,
            getattr(command, "event_id", None),
            getattr(command, "trace_id", None),
            getattr(command, "task_id", None),
            getattr(command, "trip_id", None),
        )
        fallback_result = (
            await self._fallback.plan(command)
            if operation == "plan"
            else await self._fallback.replan(command)
        )
        return replace(
            fallback_result,
            requested_provider_mode=self._provider_mode.value,
            primary_provider="AMAP",
            actual_providers=(fallback_result.provider,),
            fallback_attempted=True,
            fallback_succeeded=True,
            fallback_reason=error.details.error_code,
            fallback_operations=(
                FallbackOperation(
                    operation="PLANNING" if operation == "plan" else "REPLANNING",
                    transit_id=None,
                    from_activity_id=None,
                    to_activity_id=None,
                    requested_mode="REAL_WITH_EXPLICIT_FALLBACK",
                    actual_provider="DEMO",
                    error_category=error.details.category.value,
                    error_code=error.details.error_code,
                    retry_count=error.details.retry_count,
                ),
            ),
        )
