import asyncio
from datetime import UTC, datetime

import pytest

from trip_agent.providers.errors import ProviderErrorCategory
from trip_agent.providers.map import PoiSearchRequest, ProviderFailure, ProviderSuccess
from trip_agent.providers.retry import ProviderRetryPolicy, RetryingMapProvider


def _failure(
    category: ProviderErrorCategory,
    *,
    retryable: bool,
    retry_after_seconds: float | None = None,
) -> ProviderFailure:
    return ProviderFailure(
        provider="AMAP",
        error_code="PROVIDER_TIMEOUT",
        error_message="Safe failure",
        category=category,
        operation="POI_SEARCH",
        retryable=retryable,
        retry_after_seconds=retry_after_seconds,
        latency_ms=1,
        fetched_at=datetime(2026, 7, 31, tzinfo=UTC),
    )


def test_retrying_provider_performs_two_retries_and_reports_the_count() -> None:
    class Provider:
        calls = 0

        async def search_pois(self, _request: object) -> ProviderFailure:
            self.calls += 1
            return _failure(ProviderErrorCategory.TIMEOUT, retryable=True)

    delays: list[float] = []

    async def sleeper(delay: float) -> None:
        delays.append(delay)

    delegate = Provider()
    provider = RetryingMapProvider(
        delegate,
        ProviderRetryPolicy(
            max_attempts=3,
            base_delay_seconds=0.1,
            max_delay_seconds=1,
            max_elapsed_seconds=5,
            jitter_ratio=0,
        ),
        sleeper=sleeper,
    )

    result = asyncio.run(provider.search_pois(PoiSearchRequest(city="Guangzhou", keyword="museum")))

    assert isinstance(result, ProviderFailure)
    assert delegate.calls == 3
    assert delays == [0.1, 0.2]
    assert result.retry_count == 2
    assert result.retry_exhausted is True


def test_retrying_provider_honors_retry_after_and_stops_after_success() -> None:
    class Provider:
        calls = 0

        async def search_pois(self, _request: object):
            self.calls += 1
            if self.calls == 1:
                return _failure(
                    ProviderErrorCategory.RATE_LIMITED,
                    retryable=True,
                    retry_after_seconds=0.75,
                )
            return ProviderSuccess(
                data=(),
                provider="AMAP",
                latency_ms=1,
                cached=False,
                fetched_at=datetime(2026, 7, 31, tzinfo=UTC),
                estimated=False,
            )

    delays: list[float] = []

    async def sleeper(delay: float) -> None:
        delays.append(delay)

    delegate = Provider()
    provider = RetryingMapProvider(
        delegate,
        ProviderRetryPolicy(jitter_ratio=0),
        sleeper=sleeper,
    )

    result = asyncio.run(provider.search_pois(PoiSearchRequest(city="Guangzhou", keyword="museum")))

    assert isinstance(result, ProviderSuccess)
    assert delegate.calls == 2
    assert delays == [0.75]


def test_retry_jitter_never_exceeds_the_configured_delay_cap() -> None:
    class Provider:
        calls = 0

        async def search_pois(self, _request: object) -> ProviderFailure:
            self.calls += 1
            return _failure(ProviderErrorCategory.TIMEOUT, retryable=True)

    delays: list[float] = []

    async def sleeper(delay: float) -> None:
        delays.append(delay)

    provider = RetryingMapProvider(
        Provider(),
        ProviderRetryPolicy(
            max_attempts=2,
            base_delay_seconds=2,
            max_delay_seconds=2,
            max_elapsed_seconds=5,
            jitter_ratio=1,
        ),
        sleeper=sleeper,
        random_value=lambda: 1,
    )

    asyncio.run(provider.search_pois(PoiSearchRequest(city="Guangzhou", keyword="museum")))

    assert delays == [2]


def test_non_retryable_failure_is_called_once() -> None:
    class Provider:
        calls = 0

        async def search_pois(self, _request: object) -> ProviderFailure:
            self.calls += 1
            return _failure(
                ProviderErrorCategory.AUTHENTICATION_ERROR,
                retryable=False,
            )

    delegate = Provider()
    provider = RetryingMapProvider(delegate, ProviderRetryPolicy())

    result = asyncio.run(provider.search_pois(PoiSearchRequest(city="Guangzhou", keyword="museum")))

    assert isinstance(result, ProviderFailure)
    assert delegate.calls == 1
    assert result.retry_count == 0
    assert result.retry_exhausted is False


@pytest.mark.parametrize(
    "category",
    [
        ProviderErrorCategory.CONFIGURATION_ERROR,
        ProviderErrorCategory.AUTHENTICATION_ERROR,
        ProviderErrorCategory.PERMISSION_DENIED,
        ProviderErrorCategory.QUOTA_EXCEEDED,
        ProviderErrorCategory.INVALID_REQUEST,
        ProviderErrorCategory.UNSUPPORTED_MODE,
        ProviderErrorCategory.PROVIDER_ADAPTER_ERROR,
        ProviderErrorCategory.INTERNAL_ERROR,
    ],
)
def test_permanent_categories_are_never_retried_even_if_mislabeled_retryable(
    category: ProviderErrorCategory,
) -> None:
    class Provider:
        calls = 0

        async def search_pois(self, _request: object) -> ProviderFailure:
            self.calls += 1
            return _failure(category, retryable=True)

    delegate = Provider()
    provider = RetryingMapProvider(delegate, ProviderRetryPolicy())

    result = asyncio.run(
        provider.search_pois(PoiSearchRequest(city="Guangzhou", keyword="museum"))
    )

    assert isinstance(result, ProviderFailure)
    assert delegate.calls == 1
    assert result.retry_count == 0
    assert result.retry_exhausted is False


@pytest.mark.parametrize(
    "category",
    [
        ProviderErrorCategory.RATE_LIMITED,
        ProviderErrorCategory.TIMEOUT,
        ProviderErrorCategory.NETWORK_ERROR,
        ProviderErrorCategory.PROVIDER_UNAVAILABLE,
        ProviderErrorCategory.MALFORMED_RESPONSE,
    ],
)
def test_every_transient_category_uses_the_bounded_attempt_budget(
    category: ProviderErrorCategory,
) -> None:
    class Provider:
        calls = 0

        async def search_pois(self, _request: object) -> ProviderFailure:
            self.calls += 1
            return _failure(category, retryable=True)

    async def no_wait(_delay: float) -> None:
        return None

    delegate = Provider()
    provider = RetryingMapProvider(
        delegate,
        ProviderRetryPolicy(max_attempts=3, jitter_ratio=0),
        sleeper=no_wait,
    )

    result = asyncio.run(
        provider.search_pois(PoiSearchRequest(city="Guangzhou", keyword="museum"))
    )

    assert isinstance(result, ProviderFailure)
    assert delegate.calls == 3
    assert result.retry_count == 2
    assert result.retry_exhausted is True
