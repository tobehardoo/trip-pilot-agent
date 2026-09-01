"""Source-aware rate limiting and bounded retry orchestration."""

import asyncio
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol

from trip_agent.acquisition.fetch_models import (
    AcquisitionFetchError,
    FetchErrorCode,
    FetchResult,
    FetchValidators,
)
from trip_agent.acquisition.models import DiscoveredResource, KnowledgeSource


class AcquisitionFetcher(Protocol):
    async def fetch(
        self,
        *,
        source: KnowledgeSource,
        resource: DiscoveredResource,
        validators: FetchValidators | None = None,
    ) -> FetchResult: ...


class AsyncSleeper(Protocol):
    async def sleep(self, seconds: float) -> None: ...


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 3
    initial_backoff_seconds: float = 1.0
    max_backoff_seconds: float = 30.0

    def __post_init__(self) -> None:
        if (
            not isinstance(self.max_attempts, int)
            or isinstance(self.max_attempts, bool)
            or not 1 <= self.max_attempts <= 10
        ):
            raise ValueError("max_attempts must be between 1 and 10")
        initial = _require_positive_seconds(
            self.initial_backoff_seconds,
            "initial_backoff_seconds",
        )
        maximum = _require_positive_seconds(
            self.max_backoff_seconds,
            "max_backoff_seconds",
        )
        if maximum < initial:
            raise ValueError("max_backoff_seconds cannot be less than initial_backoff_seconds")
        object.__setattr__(self, "initial_backoff_seconds", initial)
        object.__setattr__(self, "max_backoff_seconds", maximum)

    def backoff_after(self, failed_attempt_number: int) -> float:
        return min(
            self.initial_backoff_seconds * (2 ** (failed_attempt_number - 1)),
            self.max_backoff_seconds,
        )


@dataclass(frozen=True, slots=True)
class FetchAttemptSucceeded:
    status: Literal["SUCCEEDED"]
    attempt_number: int
    started_at: datetime
    completed_at: datetime


@dataclass(frozen=True, slots=True)
class FetchAttemptFailed:
    status: Literal["FAILED"]
    attempt_number: int
    started_at: datetime
    completed_at: datetime
    error_code: FetchErrorCode
    message: str
    retryable: bool
    status_code: int | None


type FetchAttempt = FetchAttemptSucceeded | FetchAttemptFailed


@dataclass(frozen=True, slots=True)
class FetchExecutionSucceeded:
    status: Literal["SUCCEEDED"]
    result: FetchResult
    attempts: tuple[FetchAttempt, ...]


@dataclass(frozen=True, slots=True)
class FetchExecutionFailed:
    status: Literal["FAILED"]
    failure: FetchAttemptFailed
    attempts: tuple[FetchAttempt, ...]


type FetchExecution = FetchExecutionSucceeded | FetchExecutionFailed


class AcquisitionScheduler:
    def __init__(
        self,
        *,
        fetcher: AcquisitionFetcher,
        retry_policy: RetryPolicy | None = None,
        sleeper: AsyncSleeper | None = None,
        monotonic: Callable[[], float] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._fetcher = fetcher
        self._retry_policy = retry_policy or RetryPolicy()
        self._sleeper = sleeper or _AsyncioSleeper()
        self._clock = clock or _utc_now
        self._rate_limiter = _SourceRateLimiter(
            sleeper=self._sleeper,
            monotonic=monotonic or time.monotonic,
        )

    async def execute(
        self,
        *,
        source: KnowledgeSource,
        resource: DiscoveredResource,
        validators: FetchValidators | None = None,
    ) -> FetchExecution:
        attempts: list[FetchAttempt] = []
        for attempt_number in range(1, self._retry_policy.max_attempts + 1):
            await self._rate_limiter.acquire(
                source_id=source.source_id,
                interval_seconds=source.min_request_interval_seconds,
            )
            started_at = _require_aware_datetime(self._clock())
            try:
                result = await self._fetcher.fetch(
                    source=source,
                    resource=resource,
                    validators=validators,
                )
            except AcquisitionFetchError as error:
                failure = FetchAttemptFailed(
                    status="FAILED",
                    attempt_number=attempt_number,
                    started_at=started_at,
                    completed_at=_require_aware_datetime(self._clock()),
                    error_code=error.code,
                    message=str(error),
                    retryable=error.retryable,
                    status_code=error.status_code,
                )
                attempts.append(failure)
                if not error.retryable or attempt_number == self._retry_policy.max_attempts:
                    return FetchExecutionFailed(
                        status="FAILED",
                        failure=failure,
                        attempts=tuple(attempts),
                    )
                await self._sleeper.sleep(self._retry_policy.backoff_after(attempt_number))
                continue

            attempts.append(
                FetchAttemptSucceeded(
                    status="SUCCEEDED",
                    attempt_number=attempt_number,
                    started_at=started_at,
                    completed_at=_require_aware_datetime(self._clock()),
                )
            )
            return FetchExecutionSucceeded(
                status="SUCCEEDED",
                result=result,
                attempts=tuple(attempts),
            )
        raise AssertionError("retry loop exhausted without returning")


class _SourceRateLimiter:
    def __init__(
        self,
        *,
        sleeper: AsyncSleeper,
        monotonic: Callable[[], float],
    ) -> None:
        self._sleeper = sleeper
        self._monotonic = monotonic
        self._registry_lock = asyncio.Lock()
        self._lock_by_source: dict[str, asyncio.Lock] = {}
        self._last_admitted_by_source: dict[str, float] = {}

    async def acquire(self, *, source_id: str, interval_seconds: float) -> None:
        source_lock = await self._source_lock(source_id)
        async with source_lock:
            last_admitted = self._last_admitted_by_source.get(source_id)
            if last_admitted is not None:
                while True:
                    delay = last_admitted + interval_seconds - self._monotonic()
                    if delay <= 0:
                        break
                    await self._sleeper.sleep(delay)
            self._last_admitted_by_source[source_id] = self._monotonic()

    async def _source_lock(self, source_id: str) -> asyncio.Lock:
        async with self._registry_lock:
            return self._lock_by_source.setdefault(source_id, asyncio.Lock())


class _AsyncioSleeper:
    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


def _require_positive_seconds(value: object, field_name: str) -> float:
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be positive")
    normalized = float(value)
    if normalized <= 0 or not math.isfinite(normalized):
        raise ValueError(f"{field_name} must be finite and positive")
    return normalized


def _require_aware_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("scheduler clock must return a timezone-aware datetime")
    return value.astimezone(UTC)


def _utc_now() -> datetime:
    return datetime.now(UTC)
