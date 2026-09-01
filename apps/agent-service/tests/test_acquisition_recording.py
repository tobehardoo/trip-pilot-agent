import asyncio
import hashlib
from datetime import UTC, datetime, timedelta, timezone

import pytest

from trip_agent.acquisition import (
    AcquisitionExecutionRecorder,
    AcquisitionPersisted,
    AcquisitionWorkflow,
    ConditionalResourceState,
    FetchAttemptFailed,
    FetchAttemptSucceeded,
    FetchExecutionFailed,
    FetchExecutionSucceeded,
    FetchValidators,
    ResourceFetched,
    ResourceNotModified,
)
from trip_agent.acquisition.models import DiscoveredResource, KnowledgeSource
from trip_agent.acquisition.recording import AcquisitionRecord


def _source() -> KnowledgeSource:
    return KnowledgeSource(
        source_id="guangzhou-official",
        city="广州",
        source_name="广州文旅",
        reliability_level="OFFICIAL",
        allowed_domains=("wglj.gz.gov.cn",),
        resource_urls=("https://wglj.gz.gov.cn/visit/article.html",),
        max_response_bytes=64 * 1024,
    )


def _resource() -> DiscoveredResource:
    source = _source()
    return DiscoveredResource(
        source_id=source.source_id,
        city=source.city,
        url=source.resource_urls[0],
    )


class _RecordingRepository:
    def __init__(self, state: ConditionalResourceState | None = None) -> None:
        self.records: list[AcquisitionRecord] = []
        self.state = state

    async def get_conditional_state(
        self,
        resource_id: str,
    ) -> ConditionalResourceState | None:
        return self.state

    async def record(self, record: AcquisitionRecord) -> AcquisitionPersisted:
        self.records.append(record)
        return AcquisitionPersisted(
            resource_id=record.resource.resource_id,
            run_id=record.run.run_id,
            snapshot_id=record.run.snapshot_id,
            snapshot_created=record.snapshot is not None,
        )


def _successful_attempt(
    *,
    attempt_number: int = 1,
    started_at: datetime = datetime(2026, 7, 22, 1, tzinfo=UTC),
    completed_at: datetime = datetime(2026, 7, 22, 1, 0, 1, tzinfo=UTC),
) -> FetchAttemptSucceeded:
    return FetchAttemptSucceeded(
        status="SUCCEEDED",
        attempt_number=attempt_number,
        started_at=started_at,
        completed_at=completed_at,
    )


def _failed_attempt(
    *,
    attempt_number: int = 1,
    started_at: datetime = datetime(2026, 7, 22, 1, tzinfo=UTC),
    completed_at: datetime = datetime(2026, 7, 22, 1, 0, 1, tzinfo=UTC),
    retryable: bool = True,
) -> FetchAttemptFailed:
    return FetchAttemptFailed(
        status="FAILED",
        attempt_number=attempt_number,
        started_at=started_at,
        completed_at=completed_at,
        error_code="REQUEST_TIMEOUT",
        message="official page timed out",
        retryable=retryable,
        status_code=None,
    )


def test_recorder_builds_an_immutable_candidate_and_preserves_attempts() -> None:
    source = _source()
    resource = _resource()
    repository = _RecordingRepository()
    recorder = AcquisitionExecutionRecorder(
        repository=repository,
        run_id_factory=lambda: "run-001",
    )
    first_failure = _failed_attempt()
    success = _successful_attempt(
        attempt_number=2,
        started_at=datetime(2026, 7, 22, 1, 0, 2, tzinfo=UTC),
        completed_at=datetime(2026, 7, 22, 1, 0, 3, tzinfo=UTC),
    )
    fetched_at = datetime(2026, 7, 22, 9, 0, 2, tzinfo=timezone(timedelta(hours=8)))
    execution = FetchExecutionSucceeded(
        status="SUCCEEDED",
        result=ResourceFetched(
            status="FETCHED",
            requested_url=resource.url,
            final_url="https://wglj.gz.gov.cn/visit/final.html",
            fetched_at=fetched_at,
            content=b"<html>official content</html>",
            content_type="text/html; charset=utf-8",
            validators=FetchValidators(
                etag='"revision-2"',
                last_modified="Wed, 22 Jul 2026 01:00:00 GMT",
            ),
        ),
        attempts=(first_failure, success),
    )

    persisted = asyncio.run(
        recorder.record(
            source=source,
            resource=resource,
            execution=execution,
            parser_version="raw-http-v1",
            published_at=datetime(2026, 7, 20, 8, tzinfo=timezone(timedelta(hours=8))),
        )
    )

    record = repository.records[0]
    expected_content_hash = hashlib.sha256(b"<html>official content</html>").hexdigest()
    expected_resource_id = hashlib.sha256(
        f"{source.source_id}\0{resource.url}".encode()
    ).hexdigest()
    assert persisted.snapshot_created is True
    assert persisted.resource_id == expected_resource_id
    assert record.resource.last_verified_at == datetime(2026, 7, 22, 1, 0, 2, tzinfo=UTC)
    assert record.resource.last_changed_at == record.resource.last_verified_at
    assert record.snapshot is not None
    assert record.snapshot.content_hash == expected_content_hash
    assert record.snapshot.parser_version == "raw-http-v1"
    assert record.snapshot.review_status == "PENDING"
    assert record.snapshot.published_at == datetime(2026, 7, 20, tzinfo=UTC)
    assert record.run.run_id == "run-001"
    assert record.run.status == "FETCHED"
    assert record.run.attempt_count == 2
    assert record.run.started_at == first_failure.started_at
    assert record.run.completed_at == success.completed_at
    assert record.run.attempts[0].error_code == "REQUEST_TIMEOUT"
    assert record.run.snapshot_id == record.snapshot.snapshot_id


def test_recorder_records_not_modified_without_creating_a_snapshot() -> None:
    source = _source()
    resource = _resource()
    repository = _RecordingRepository()
    recorder = AcquisitionExecutionRecorder(
        repository=repository,
        run_id_factory=lambda: "run-304",
    )
    fetched_at = datetime(2026, 7, 22, 2, tzinfo=UTC)
    base_content_hash = hashlib.sha256(b"current content").hexdigest()
    execution = FetchExecutionSucceeded(
        status="SUCCEEDED",
        result=ResourceNotModified(
            status="NOT_MODIFIED",
            requested_url=resource.url,
            final_url=resource.url,
            fetched_at=fetched_at,
            validators=FetchValidators(etag='"revision-2"'),
        ),
        attempts=(_successful_attempt(),),
    )

    persisted = asyncio.run(
        recorder.record(
            source=source,
            resource=resource,
            execution=execution,
            parser_version="raw-http-v1",
            base_content_hash=base_content_hash,
        )
    )

    record = repository.records[0]
    assert persisted.snapshot_created is False
    assert persisted.snapshot_id is None
    assert record.snapshot is None
    assert record.resource.last_verified_at == fetched_at
    assert record.resource.last_changed_at is None
    assert record.resource.current_content_hash == base_content_hash
    assert record.run.status == "NOT_MODIFIED"
    assert record.run.snapshot_id is None


def test_workflow_loads_validators_and_always_records_the_scheduler_result() -> None:
    source = _source()
    resource = _resource()
    validators = FetchValidators(etag='"current"')
    base_content_hash = hashlib.sha256(b"current content").hexdigest()
    state = ConditionalResourceState(
        validators=validators,
        content_hash=base_content_hash,
    )
    repository = _RecordingRepository(state)
    recorder = AcquisitionExecutionRecorder(
        repository=repository,
        run_id_factory=lambda: "workflow-run",
    )
    execution = FetchExecutionSucceeded(
        status="SUCCEEDED",
        result=ResourceNotModified(
            status="NOT_MODIFIED",
            requested_url=resource.url,
            final_url=resource.url,
            fetched_at=datetime(2026, 7, 22, 2, tzinfo=UTC),
            validators=validators,
        ),
        attempts=(_successful_attempt(),),
    )

    class _Scheduler:
        def __init__(self) -> None:
            self.validators: FetchValidators | None = None

        async def execute(
            self,
            *,
            source: KnowledgeSource,
            resource: DiscoveredResource,
            validators: FetchValidators | None = None,
        ) -> FetchExecutionSucceeded:
            self.validators = validators
            return execution

    scheduler = _Scheduler()
    workflow = AcquisitionWorkflow(
        scheduler=scheduler,
        recorder=recorder,
        parser_version="raw-http-v1",
    )

    result = asyncio.run(workflow.execute(source=source, resource=resource))

    assert scheduler.validators == validators
    assert result.execution is execution
    assert result.persisted.run_id == "workflow-run"
    assert repository.records[0].run.status == "NOT_MODIFIED"
    assert repository.records[0].resource.current_content_hash == base_content_hash


def test_recorder_rejects_not_modified_without_the_conditional_base_hash() -> None:
    source = _source()
    resource = _resource()
    recorder = AcquisitionExecutionRecorder(repository=_RecordingRepository())
    execution = FetchExecutionSucceeded(
        status="SUCCEEDED",
        result=ResourceNotModified(
            status="NOT_MODIFIED",
            requested_url=resource.url,
            final_url=resource.url,
            fetched_at=datetime(2026, 7, 22, 2, tzinfo=UTC),
            validators=FetchValidators(etag='"revision"'),
        ),
        attempts=(_successful_attempt(),),
    )

    with pytest.raises(ValueError, match="base_content_hash is required for NOT_MODIFIED"):
        asyncio.run(
            recorder.record(
                source=source,
                resource=resource,
                execution=execution,
                parser_version="raw-http-v1",
            )
        )


@pytest.mark.parametrize(
    ("resource_url", "message"),
    [
        (
            "HTTPS://WGLJ.GZ.GOV.CN/visit/article.html#section",
            "resource URL must be canonical",
        ),
        (
            "https://wglj.gz.gov.cn/visit/unmanaged.html",
            "resource URL must be registered for the source",
        ),
    ],
)
def test_recorder_rejects_noncanonical_or_unmanaged_resources(
    resource_url: str,
    message: str,
) -> None:
    source = _source()
    resource = DiscoveredResource(
        source_id=source.source_id,
        city=source.city,
        url=resource_url,
    )
    recorder = AcquisitionExecutionRecorder(repository=_RecordingRepository())
    failure = _failed_attempt(retryable=False)

    with pytest.raises(ValueError, match=message):
        asyncio.run(
            recorder.record(
                source=source,
                resource=resource,
                execution=FetchExecutionFailed(
                    status="FAILED",
                    failure=failure,
                    attempts=(failure,),
                ),
                parser_version="raw-http-v1",
            )
        )


def test_recorder_rejects_a_successful_result_with_an_unsafe_final_url() -> None:
    source = _source()
    resource = _resource()
    recorder = AcquisitionExecutionRecorder(repository=_RecordingRepository())
    execution = FetchExecutionSucceeded(
        status="SUCCEEDED",
        result=ResourceNotModified(
            status="NOT_MODIFIED",
            requested_url=resource.url,
            final_url="https://unmanaged.example.com/article.html",
            fetched_at=datetime(2026, 7, 22, 2, tzinfo=UTC),
            validators=FetchValidators(etag='"revision"'),
        ),
        attempts=(_successful_attempt(),),
    )

    with pytest.raises(ValueError, match="outside the allowed domain"):
        asyncio.run(
            recorder.record(
                source=source,
                resource=resource,
                execution=execution,
                parser_version="raw-http-v1",
            )
        )


def test_recorder_records_failure_without_marking_the_resource_verified() -> None:
    source = _source()
    resource = _resource()
    repository = _RecordingRepository()
    recorder = AcquisitionExecutionRecorder(
        repository=repository,
        run_id_factory=lambda: "run-failed",
    )
    failure = _failed_attempt(retryable=False)
    execution = FetchExecutionFailed(
        status="FAILED",
        failure=failure,
        attempts=(failure,),
    )

    asyncio.run(
        recorder.record(
            source=source,
            resource=resource,
            execution=execution,
            parser_version="raw-http-v1",
        )
    )

    record = repository.records[0]
    assert record.snapshot is None
    assert record.resource.last_verified_at is None
    assert record.resource.last_changed_at is None
    assert record.run.status == "FAILED"
    assert record.run.error_code == "REQUEST_TIMEOUT"
    assert record.run.error_message == "official page timed out"
    assert record.run.retryable is False
    assert record.run.snapshot_id is None


def test_recorder_rejects_an_execution_whose_final_attempt_does_not_match_status() -> None:
    source = _source()
    resource = _resource()
    repository = _RecordingRepository()
    recorder = AcquisitionExecutionRecorder(repository=repository)
    failure = _failed_attempt()
    execution = FetchExecutionSucceeded(
        status="SUCCEEDED",
        result=ResourceNotModified(
            status="NOT_MODIFIED",
            requested_url=resource.url,
            final_url=resource.url,
            fetched_at=datetime(2026, 7, 22, 2, tzinfo=UTC),
            validators=FetchValidators(etag='"revision"'),
        ),
        attempts=(failure,),
    )

    with pytest.raises(ValueError, match="successful execution must end with a successful attempt"):
        asyncio.run(
            recorder.record(
                source=source,
                resource=resource,
                execution=execution,
                parser_version="raw-http-v1",
            )
        )


def test_recorder_rejects_attempts_with_an_overlapping_timeline() -> None:
    source = _source()
    resource = _resource()
    repository = _RecordingRepository()
    recorder = AcquisitionExecutionRecorder(repository=repository)
    failure = _failed_attempt(
        completed_at=datetime(2026, 7, 22, 1, 0, 3, tzinfo=UTC)
    )
    success = _successful_attempt(
        attempt_number=2,
        started_at=datetime(2026, 7, 22, 1, 0, 2, tzinfo=UTC),
        completed_at=datetime(2026, 7, 22, 1, 0, 4, tzinfo=UTC),
    )
    execution = FetchExecutionSucceeded(
        status="SUCCEEDED",
        result=ResourceNotModified(
            status="NOT_MODIFIED",
            requested_url=resource.url,
            final_url=resource.url,
            fetched_at=datetime(2026, 7, 22, 1, 0, 3, tzinfo=UTC),
            validators=FetchValidators(etag='"revision"'),
        ),
        attempts=(failure, success),
    )

    with pytest.raises(ValueError, match="attempt timeline cannot overlap"):
        asyncio.run(
            recorder.record(
                source=source,
                resource=resource,
                execution=execution,
                parser_version="raw-http-v1",
            )
        )


@pytest.mark.parametrize(
    ("source", "resource", "parser_version", "published_at", "message"),
    [
        (_source(), _resource(), " ", None, "parser_version cannot be empty"),
        (
            _source(),
            DiscoveredResource(
                source_id="another-source",
                city="广州",
                url=_resource().url,
            ),
            "raw-http-v1",
            None,
            "resource source_id must match source",
        ),
        (
            _source(),
            _resource(),
            "raw-http-v1",
            datetime(2026, 7, 20),
            "published_at must be timezone-aware",
        ),
    ],
)
def test_recorder_rejects_invalid_recording_metadata(
    source: KnowledgeSource,
    resource: DiscoveredResource,
    parser_version: str,
    published_at: datetime | None,
    message: str,
) -> None:
    repository = _RecordingRepository()
    recorder = AcquisitionExecutionRecorder(repository=repository)
    execution = FetchExecutionSucceeded(
        status="SUCCEEDED",
        result=ResourceNotModified(
            status="NOT_MODIFIED",
            requested_url=resource.url,
            final_url=resource.url,
            fetched_at=datetime(2026, 7, 22, 2, tzinfo=UTC),
            validators=FetchValidators(etag='"revision"'),
        ),
        attempts=(_successful_attempt(),),
    )

    with pytest.raises(ValueError, match=message):
        asyncio.run(
            recorder.record(
                source=source,
                resource=resource,
                execution=execution,
                parser_version=parser_version,
                published_at=published_at,
            )
        )
