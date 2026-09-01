"""Bounded retries for map and route providers."""

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import monotonic
from typing import TypeVar

from trip_agent.providers.errors import ProviderErrorCategory
from trip_agent.providers.map import (
    MapProvider,
    PoiSearchRequest,
    PoiSearchResult,
    ProviderFailure,
)
from trip_agent.providers.route import RouteProvider, RouteRequest, RouteResult

logger = logging.getLogger(__name__)

ResultT = TypeVar("ResultT", PoiSearchResult, RouteResult)


@dataclass(frozen=True, slots=True)
class ProviderRetryPolicy:
    max_attempts: int = 3
    base_delay_seconds: float = 0.2
    max_delay_seconds: float = 2.0
    max_elapsed_seconds: float = 5.0
    jitter_ratio: float = 0.2

    def __post_init__(self) -> None:
        if self.max_attempts < 1 or self.max_attempts > 5:
            raise ValueError("max_attempts must be between 1 and 5")
        if self.base_delay_seconds < 0 or self.max_delay_seconds < 0:
            raise ValueError("retry delays cannot be negative")
        if self.max_elapsed_seconds <= 0:
            raise ValueError("max_elapsed_seconds must be positive")
        if not 0 <= self.jitter_ratio <= 1:
            raise ValueError("jitter_ratio must be between 0 and 1")


class RetryingMapProvider:
    def __init__(
        self,
        delegate: MapProvider,
        policy: ProviderRetryPolicy,
        *,
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = monotonic,
        random_value: Callable[[], float] = random.random,
    ) -> None:
        self._delegate = delegate
        self._executor = _RetryExecutor(policy, sleeper, clock, random_value)

    async def search_pois(self, request: PoiSearchRequest) -> PoiSearchResult:
        return await self._executor.execute(
            lambda: self._delegate.search_pois(request),
            operation="POI_SEARCH",
        )


class RetryingRouteProvider:
    def __init__(
        self,
        delegate: RouteProvider,
        policy: ProviderRetryPolicy,
        *,
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = monotonic,
        random_value: Callable[[], float] = random.random,
    ) -> None:
        self._delegate = delegate
        self._executor = _RetryExecutor(policy, sleeper, clock, random_value)

    async def get_route(self, request: RouteRequest) -> RouteResult:
        return await self._executor.execute(
            lambda: self._delegate.get_route(request),
            operation="ROUTE",
        )


class _RetryExecutor:
    _retryable_categories = frozenset(
        {
            ProviderErrorCategory.RATE_LIMITED,
            ProviderErrorCategory.TIMEOUT,
            ProviderErrorCategory.NETWORK_ERROR,
            ProviderErrorCategory.PROVIDER_UNAVAILABLE,
            ProviderErrorCategory.MALFORMED_RESPONSE,
        }
    )

    def __init__(
        self,
        policy: ProviderRetryPolicy,
        sleeper: Callable[[float], Awaitable[None]],
        clock: Callable[[], float],
        random_value: Callable[[], float],
    ) -> None:
        self._policy = policy
        self._sleep = sleeper
        self._clock = clock
        self._random = random_value

    async def execute(
        self,
        call: Callable[[], Awaitable[ResultT]],
        *,
        operation: str,
    ) -> ResultT:
        started_at = self._clock()
        for attempt in range(1, self._policy.max_attempts + 1):
            result = await call()
            if not isinstance(result, ProviderFailure):
                return result
            retry_count = attempt - 1
            can_retry = (
                result.retryable
                and result.category in self._retryable_categories
                and attempt < self._policy.max_attempts
            )
            if not can_retry:
                exhausted = (
                    result.retryable
                    and result.category in self._retryable_categories
                    and attempt >= self._policy.max_attempts
                )
                return result.model_copy(
                    update={
                        "retry_count": retry_count,
                        "retry_exhausted": exhausted,
                    }
                )
            delay = self._delay(result, retry_count)
            if self._clock() - started_at + delay > self._policy.max_elapsed_seconds:
                return result.model_copy(
                    update={
                        "retry_count": retry_count,
                        "retry_exhausted": True,
                    }
                )
            logger.warning(
                "provider_retry operation=%s provider=%s category=%s retry_count=%s delay=%.3f",
                operation,
                result.provider,
                result.category,
                attempt,
                delay,
            )
            await self._sleep(delay)
        raise AssertionError("retry loop must return")

    def _delay(self, failure: ProviderFailure, retry_count: int) -> float:
        backoff = min(
            self._policy.max_delay_seconds,
            self._policy.base_delay_seconds * (2**retry_count),
        )
        if failure.retry_after_seconds is not None:
            backoff = min(
                self._policy.max_delay_seconds,
                max(backoff, failure.retry_after_seconds),
            )
        jitter = backoff * self._policy.jitter_ratio * self._random()
        return min(self._policy.max_delay_seconds, backoff + jitter)
