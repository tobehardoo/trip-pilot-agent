import asyncio
from dataclasses import replace

import pytest

from trip_agent.domain.planning.protocols import PlanningProviderError, PlanningResult
from trip_agent.providers.errors import (
    FallbackDecision,
    ProviderErrorCategory,
    ProviderExecutionMode,
    ProviderFailureDetails,
    ProviderFallbackPolicy,
    ProviderOperation,
)
from trip_agent.workflow.planner_pipeline import FallbackPlanningProvider


def _details(category: ProviderErrorCategory) -> ProviderFailureDetails:
    return ProviderFailureDetails(
        category=category,
        error_code=f"TEST_{category.value}",
        provider="AMAP",
        operation=ProviderOperation.PLANNING,
        retryable=category in {
            ProviderErrorCategory.TIMEOUT,
            ProviderErrorCategory.RATE_LIMITED,
        },
        fallback_allowed=False,
        safe_provider_code=None,
        safe_message="Safe provider failure",
        retry_count=2,
        cause_type=None,
        retry_exhausted=True,
    )


@pytest.mark.parametrize(
    "category",
    [
        ProviderErrorCategory.CONFIGURATION_ERROR,
        ProviderErrorCategory.AUTHENTICATION_ERROR,
        ProviderErrorCategory.PERMISSION_DENIED,
        ProviderErrorCategory.INVALID_REQUEST,
        ProviderErrorCategory.PROVIDER_ADAPTER_ERROR,
        ProviderErrorCategory.INTERNAL_ERROR,
    ],
)
def test_explicit_fallback_policy_denies_permanent_and_internal_errors(
    category: ProviderErrorCategory,
) -> None:
    policy = ProviderFallbackPolicy()

    assert policy.decide(
        ProviderExecutionMode.REAL_WITH_EXPLICIT_FALLBACK,
        _details(category),
    ) == FallbackDecision.DENY_FALLBACK


def test_explicit_fallback_policy_allows_exhausted_transient_errors_only() -> None:
    policy = ProviderFallbackPolicy()
    timeout = _details(ProviderErrorCategory.TIMEOUT)

    assert policy.decide(
        ProviderExecutionMode.REAL_WITH_EXPLICIT_FALLBACK,
        timeout,
    ) == FallbackDecision.ALLOW_FALLBACK
    assert policy.decide(
        ProviderExecutionMode.REAL_ONLY,
        timeout,
    ) == FallbackDecision.DENY_FALLBACK
    assert policy.decide(
        ProviderExecutionMode.REAL_WITH_EXPLICIT_FALLBACK,
        replace(timeout, retry_exhausted=False),
    ) == FallbackDecision.DENY_FALLBACK


def test_quota_and_malformed_fallback_require_an_explicit_allowlist() -> None:
    quota = _details(ProviderErrorCategory.QUOTA_EXCEEDED)
    malformed = replace(
        _details(ProviderErrorCategory.MALFORMED_RESPONSE),
        retryable=True,
    )

    default_policy = ProviderFallbackPolicy()
    configured_policy = ProviderFallbackPolicy(
        additional_allowed_categories=frozenset(
            {
                ProviderErrorCategory.QUOTA_EXCEEDED,
                ProviderErrorCategory.MALFORMED_RESPONSE,
            }
        )
    )

    for failure in (quota, malformed):
        assert default_policy.decide(
            ProviderExecutionMode.REAL_WITH_EXPLICIT_FALLBACK,
            failure,
        ) == FallbackDecision.DENY_FALLBACK
        assert configured_policy.decide(
            ProviderExecutionMode.REAL_WITH_EXPLICIT_FALLBACK,
            failure,
        ) == FallbackDecision.ALLOW_FALLBACK


def test_fallback_allowlist_rejects_permanent_and_internal_categories() -> None:
    with pytest.raises(ValueError, match="cannot be enabled for fallback"):
        ProviderFallbackPolicy(
            additional_allowed_categories=frozenset(
                {ProviderErrorCategory.AUTHENTICATION_ERROR}
            )
        )


def test_planning_fallback_wrapper_uses_the_central_policy() -> None:
    class Primary:
        async def plan(self, _command: object) -> PlanningResult:
            raise PlanningProviderError(_details(ProviderErrorCategory.TIMEOUT))

        async def replan(self, _command: object) -> PlanningResult:
            raise AssertionError

    class Fallback:
        calls = 0

        async def plan(self, _command: object) -> PlanningResult:
            self.calls += 1
            return PlanningResult(provider="DEMO", itinerary=[])

        async def replan(self, _command: object) -> PlanningResult:
            raise AssertionError

    fallback = Fallback()
    provider = FallbackPlanningProvider(
        Primary(),
        fallback,
        provider_mode=ProviderExecutionMode.REAL_WITH_EXPLICIT_FALLBACK,
        fallback_policy=ProviderFallbackPolicy(),
    )

    result = asyncio.run(provider.plan(None))

    assert result.provider == "DEMO"
    assert fallback.calls == 1


def test_planning_fallback_wrapper_does_not_hide_authentication_failure() -> None:
    class Primary:
        async def plan(self, _command: object) -> PlanningResult:
            raise PlanningProviderError(
                _details(ProviderErrorCategory.AUTHENTICATION_ERROR)
            )

        async def replan(self, _command: object) -> PlanningResult:
            raise AssertionError

    class Fallback:
        calls = 0

        async def plan(self, _command: object) -> PlanningResult:
            self.calls += 1
            raise AssertionError

        async def replan(self, _command: object) -> PlanningResult:
            raise AssertionError

    fallback = Fallback()
    provider = FallbackPlanningProvider(
        Primary(),
        fallback,
        provider_mode=ProviderExecutionMode.REAL_WITH_EXPLICIT_FALLBACK,
    )

    with pytest.raises(PlanningProviderError):
        asyncio.run(provider.plan(None))
    assert fallback.calls == 0
