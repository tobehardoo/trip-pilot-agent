import asyncio
from datetime import UTC, datetime, timedelta, timezone

import pytest

from trip_agent.acquisition import (
    AcquisitionFetchError,
    AcquisitionScheduler,
    FetchValidators,
    RetryPolicy,
)
from trip_agent.acquisition.fetch_models import FetchErrorCode, FetchResult, ResourceFetched
from trip_agent.acquisition.models import DiscoveredResource, KnowledgeSource


def _source(
    *,
    source_id: str = "official-source",
    min_request_interval_seconds: float = 0.5,
) -> KnowledgeSource:
    domain = f"{source_id}.example.com"
    return KnowledgeSource(
        source_id=source_id,
        city="广州",
        source_name="官方来源",
        reliability_level="OFFICIAL",
        allowed_domains=(domain,),
        resource_urls=(f"https://{domain}/article",),
        min_request_interval_seconds=min_request_interval_seconds,
        max_response_bytes=64 * 1024,
    )


def _resource(source: KnowledgeSource) -> DiscoveredResource:
    return DiscoveredResource(
        source_id=source.source_id,
        city=source.city,
        url=source.resource_urls[0],
    )


def _fetched(resource: DiscoveredResource) -> ResourceFetched:
    return ResourceFetched(
        status="FETCHED",
        requested_url=resource.url,
        final_url=resource.url,
        fetched_at=datetime(2026, 7, 22, tzinfo=UTC),
        content=b"content",
        content_type="text/html",
        validators=FetchValidators(etag='"revision"'),
    )


def _fetch_error(
    *,
    code: FetchErrorCode = "REQUEST_FAILED",
    retryable: bool = True,
    status_code: int | None = None,
) -> AcquisitionFetchError:
    return AcquisitionFetchError(
        code,
        f"fetch failed: {code}",
        retryable=retryable,
        status_code=status_code,
    )


class _ScriptedFetcher:
    def __init__(self, outcomes: list[FetchResult | AcquisitionFetchError]) -> None:
        self._outcomes = list(outcomes)
        self.validators: list[FetchValidators | None] = []

    async def fetch(
        self,
        *,
        source: KnowledgeSource,
        resource: DiscoveredResource,
        validators: FetchValidators | None = None,
    ) -> FetchResult:
        self.validators.append(validators)
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, AcquisitionFetchError):
            raise outcome
        return outcome


class _FakeTime:
    def __init__(self) -> None:
        self.seconds = 0.0
        self.sleep_calls: list[float] = []
        self._started_at = datetime(2026, 7, 22, tzinfo=UTC)

    def monotonic(self) -> float:
        return self.seconds

    def now(self) -> datetime:
        return self._started_at + timedelta(seconds=self.seconds)

    async def sleep(self, seconds: float) -> None:
        self.sleep_calls.append(seconds)
        self.seconds += seconds


def _scheduler(
    fetcher: _ScriptedFetcher,
    fake_time: _FakeTime,
    *,
    retry_policy: RetryPolicy | None = None,
) -> AcquisitionScheduler:
    return AcquisitionScheduler(
        fetcher=fetcher,
        retry_policy=retry_policy or RetryPolicy(),
        sleeper=fake_time,
        monotonic=fake_time.monotonic,
        clock=fake_time.now,
    )


def test_scheduler_retries_retryable_failures_with_capped_exponential_backoff() -> None:
    source = _source()
    resource = _resource(source)
    fake_time = _FakeTime()
    fetcher = _ScriptedFetcher(
        [
            _fetch_error(code="REQUEST_TIMEOUT"),
            _fetch_error(code="HTTP_STATUS_ERROR", status_code=503),
            _fetch_error(code="REQUEST_FAILED"),
            _fetched(resource),
        ]
    )
    scheduler = _scheduler(
        fetcher,
        fake_time,
        retry_policy=RetryPolicy(
            max_attempts=4,
            initial_backoff_seconds=1.0,
            max_backoff_seconds=2.0,
        ),
    )

    execution = asyncio.run(scheduler.execute(source=source, resource=resource))

    assert execution.status == "SUCCEEDED"
    assert execution.result.content == b"content"
    assert [attempt.status for attempt in execution.attempts] == [
        "FAILED",
        "FAILED",
        "FAILED",
        "SUCCEEDED",
    ]
    assert [execution.attempts[0].error_code, execution.attempts[1].error_code] == [
        "REQUEST_TIMEOUT",
        "HTTP_STATUS_ERROR",
    ]
    assert fake_time.sleep_calls == [1.0, 2.0, 2.0]


def test_scheduler_stops_at_attempt_limit_and_returns_final_failure() -> None:
    source = _source()
    resource = _resource(source)
    fake_time = _FakeTime()
    fetcher = _ScriptedFetcher([_fetch_error(), _fetch_error(), _fetch_error()])
    scheduler = _scheduler(
        fetcher,
        fake_time,
        retry_policy=RetryPolicy(
            max_attempts=3,
            initial_backoff_seconds=1.0,
            max_backoff_seconds=1.0,
        ),
    )

    execution = asyncio.run(scheduler.execute(source=source, resource=resource))

    assert execution.status == "FAILED"
    assert execution.failure.error_code == "REQUEST_FAILED"
    assert execution.failure.retryable is True
    assert len(execution.attempts) == 3
    assert fake_time.sleep_calls == [1.0, 1.0]


def test_scheduler_does_not_retry_non_retryable_failure() -> None:
    source = _source()
    resource = _resource(source)
    fake_time = _FakeTime()
    scheduler = _scheduler(
        _ScriptedFetcher(
            [_fetch_error(code="HTTP_STATUS_ERROR", retryable=False, status_code=404)]
        ),
        fake_time,
    )

    execution = asyncio.run(scheduler.execute(source=source, resource=resource))

    assert execution.status == "FAILED"
    assert execution.failure.status_code == 404
    assert len(execution.attempts) == 1
    assert fake_time.sleep_calls == []


def test_scheduler_rate_limits_same_source_without_blocking_another_source() -> None:
    first_source = _source(min_request_interval_seconds=2.0)
    second_source = _source(source_id="second-source", min_request_interval_seconds=2.0)
    first_resource = _resource(first_source)
    second_resource = _resource(second_source)
    fake_time = _FakeTime()
    fetcher = _ScriptedFetcher(
        [_fetched(first_resource), _fetched(first_resource), _fetched(second_resource)]
    )
    scheduler = _scheduler(fetcher, fake_time)

    async def execute_all() -> tuple[object, object, object]:
        first = await scheduler.execute(source=first_source, resource=first_resource)
        repeated = await scheduler.execute(source=first_source, resource=first_resource)
        other = await scheduler.execute(source=second_source, resource=second_resource)
        return first, repeated, other

    first, repeated, other = asyncio.run(execute_all())

    assert first.status == repeated.status == other.status == "SUCCEEDED"
    assert fake_time.sleep_calls == [2.0]
    assert repeated.attempts[0].started_at == datetime(2026, 7, 22, tzinfo=UTC) + timedelta(
        seconds=2
    )
    assert other.attempts[0].started_at == repeated.attempts[0].started_at


def test_scheduler_applies_rate_limit_to_retry_attempts_after_backoff() -> None:
    source = _source(min_request_interval_seconds=5.0)
    resource = _resource(source)
    fake_time = _FakeTime()
    scheduler = _scheduler(
        _ScriptedFetcher([_fetch_error(), _fetched(resource)]),
        fake_time,
        retry_policy=RetryPolicy(
            max_attempts=2,
            initial_backoff_seconds=1.0,
            max_backoff_seconds=1.0,
        ),
    )

    execution = asyncio.run(scheduler.execute(source=source, resource=resource))

    assert execution.status == "SUCCEEDED"
    assert fake_time.sleep_calls == [1.0, 4.0]
    assert execution.attempts[1].started_at == datetime(2026, 7, 22, tzinfo=UTC) + timedelta(
        seconds=5
    )


def test_scheduler_forwards_conditional_request_validators() -> None:
    source = _source()
    resource = _resource(source)
    validators = FetchValidators(etag='"previous"')
    fake_time = _FakeTime()
    fetcher = _ScriptedFetcher([_fetched(resource)])
    scheduler = _scheduler(fetcher, fake_time)

    execution = asyncio.run(
        scheduler.execute(source=source, resource=resource, validators=validators)
    )

    assert execution.status == "SUCCEEDED"
    assert fetcher.validators == [validators]


def test_scheduler_normalizes_attempt_timestamps_to_utc() -> None:
    source = _source()
    resource = _resource(source)
    fake_time = _FakeTime()
    scheduler = AcquisitionScheduler(
        fetcher=_ScriptedFetcher([_fetched(resource)]),
        sleeper=fake_time,
        monotonic=fake_time.monotonic,
        clock=lambda: datetime(2026, 7, 22, 8, tzinfo=timezone(timedelta(hours=8))),
    )

    execution = asyncio.run(scheduler.execute(source=source, resource=resource))

    assert execution.status == "SUCCEEDED"
    assert execution.attempts[0].started_at.tzinfo is UTC
    assert execution.attempts[0].started_at == datetime(2026, 7, 22, tzinfo=UTC)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_attempts": 0},
        {"max_attempts": 11},
        {"initial_backoff_seconds": 0},
        {"max_backoff_seconds": 0},
        {"initial_backoff_seconds": 2, "max_backoff_seconds": 1},
        {"initial_backoff_seconds": float("nan")},
        {"initial_backoff_seconds": float("inf")},
        {"max_backoff_seconds": float("nan")},
        {"max_backoff_seconds": float("inf")},
    ],
)
def test_retry_policy_rejects_invalid_bounds(kwargs: dict[str, int | float]) -> None:
    with pytest.raises(ValueError):
        RetryPolicy(**kwargs)
