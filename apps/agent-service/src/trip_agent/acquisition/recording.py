"""Application boundary for recording scheduled acquisition executions."""

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, NewType, Protocol
from uuid import uuid4

from trip_agent.acquisition.fetch_models import (
    FetchErrorCode,
    FetchValidators,
    ResourceFetched,
)
from trip_agent.acquisition.models import (
    DiscoveredResource,
    KnowledgeSource,
    ReliabilityLevel,
    resource_id_for,
)
from trip_agent.acquisition.scheduling import (
    FetchAttempt,
    FetchAttemptSucceeded,
    FetchExecution,
)
from trip_agent.acquisition.security import validate_source_url

ResourceId = NewType("ResourceId", str)
SnapshotId = NewType("SnapshotId", str)
FetchRunId = NewType("FetchRunId", str)

type FetchRunStatus = Literal["FETCHED", "NOT_MODIFIED", "FAILED"]
type ReviewStatus = Literal["PENDING"]


@dataclass(frozen=True, slots=True)
class KnowledgeResourceRecord:
    resource_id: ResourceId
    source_id: str
    source_name: str
    reliability_level: ReliabilityLevel
    city: str
    source_url: str
    final_url: str
    validators: FetchValidators | None
    current_content_hash: str | None
    last_attempted_at: datetime
    last_verified_at: datetime | None
    last_changed_at: datetime | None


@dataclass(frozen=True, slots=True)
class CandidateSnapshot:
    snapshot_id: SnapshotId
    resource_id: ResourceId
    source_url: str
    final_url: str
    fetched_at: datetime
    published_at: datetime | None
    content_hash: str
    raw_content: bytes
    content_type: str | None
    validators: FetchValidators
    parser_version: str
    review_status: ReviewStatus = "PENDING"


@dataclass(frozen=True, slots=True)
class FetchRunRecord:
    run_id: FetchRunId
    resource_id: ResourceId
    started_at: datetime
    completed_at: datetime
    status: FetchRunStatus
    attempts: tuple[FetchAttempt, ...]
    attempt_count: int
    snapshot_id: SnapshotId | None
    error_code: FetchErrorCode | None
    error_message: str | None
    retryable: bool | None
    http_status: int | None


@dataclass(frozen=True, slots=True)
class AcquisitionRecord:
    resource: KnowledgeResourceRecord
    snapshot: CandidateSnapshot | None
    run: FetchRunRecord


@dataclass(frozen=True, slots=True)
class AcquisitionPersisted:
    resource_id: ResourceId
    run_id: FetchRunId
    snapshot_id: SnapshotId | None
    snapshot_created: bool


@dataclass(frozen=True, slots=True)
class ConditionalResourceState:
    validators: FetchValidators
    content_hash: str

    def __post_init__(self) -> None:
        _require_sha256(self.content_hash, "content_hash")


class AcquisitionRecordRepository(Protocol):
    async def get_conditional_state(
        self,
        resource_id: ResourceId,
    ) -> ConditionalResourceState | None: ...

    async def record(self, record: AcquisitionRecord) -> AcquisitionPersisted: ...


class AcquisitionExecutionRecorder:
    def __init__(
        self,
        *,
        repository: AcquisitionRecordRepository,
        run_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._repository = repository
        self._run_id_factory = run_id_factory or (lambda: str(uuid4()))

    async def get_conditional_state(
        self,
        *,
        source: KnowledgeSource,
        resource: DiscoveredResource,
    ) -> ConditionalResourceState | None:
        _validate_resource(source, resource)
        return await self._repository.get_conditional_state(
            _resource_id(source.source_id, resource.url)
        )

    async def record(
        self,
        *,
        source: KnowledgeSource,
        resource: DiscoveredResource,
        execution: FetchExecution,
        parser_version: str,
        published_at: datetime | None = None,
        base_content_hash: str | None = None,
    ) -> AcquisitionPersisted:
        parser = _require_text(parser_version, "parser_version")
        published = _optional_utc(published_at, "published_at")
        _validate_resource(source, resource)
        attempts = _validate_attempts(execution.attempts)
        run_id = FetchRunId(_require_text(self._run_id_factory(), "run_id"))
        resource_id = _resource_id(source.source_id, resource.url)
        started_at = _as_utc(attempts[0].started_at, "attempt started_at")
        completed_at = _as_utc(attempts[-1].completed_at, "attempt completed_at")

        snapshot: CandidateSnapshot | None = None
        error_code: FetchErrorCode | None = None
        error_message: str | None = None
        retryable: bool | None = None
        http_status: int | None = None

        if execution.status == "FAILED":
            if execution.failure != attempts[-1]:
                raise ValueError("execution failure must be the final attempt")
            run_status: FetchRunStatus = "FAILED"
            final_url = resource.url
            validators = None
            current_content_hash = None
            verified_at = None
            changed_at = None
            error_code = execution.failure.error_code
            error_message = execution.failure.message
            retryable = execution.failure.retryable
            http_status = execution.failure.status_code
        else:
            if not isinstance(attempts[-1], FetchAttemptSucceeded):
                raise ValueError("successful execution must end with a successful attempt")
            result = execution.result
            if result.requested_url != resource.url:
                raise ValueError("fetch result requested_url must match resource URL")
            _validate_canonical_url(
                result.final_url,
                allowed_domains=source.allowed_domains,
                field_name="fetch result final_url",
            )
            verified_at = _as_utc(result.fetched_at, "fetched_at")
            final_url = result.final_url
            validators = result.validators
            if isinstance(result, ResourceFetched):
                run_status = "FETCHED"
                content_hash = hashlib.sha256(result.content).hexdigest()
                snapshot_id = _snapshot_id(resource_id, content_hash, parser)
                snapshot = CandidateSnapshot(
                    snapshot_id=snapshot_id,
                    resource_id=resource_id,
                    source_url=resource.url,
                    final_url=result.final_url,
                    fetched_at=verified_at,
                    published_at=published,
                    content_hash=content_hash,
                    raw_content=result.content,
                    content_type=result.content_type,
                    validators=result.validators,
                    parser_version=parser,
                )
                current_content_hash = content_hash
                changed_at = verified_at
            else:
                run_status = "NOT_MODIFIED"
                snapshot_id = None
                if base_content_hash is None:
                    raise ValueError("base_content_hash is required for NOT_MODIFIED")
                current_content_hash = _require_sha256(
                    base_content_hash,
                    "base_content_hash",
                )
                changed_at = None

        resource_record = KnowledgeResourceRecord(
            resource_id=resource_id,
            source_id=source.source_id,
            source_name=source.source_name,
            reliability_level=source.reliability_level,
            city=source.city,
            source_url=resource.url,
            final_url=final_url,
            validators=validators,
            current_content_hash=current_content_hash,
            last_attempted_at=completed_at,
            last_verified_at=verified_at,
            last_changed_at=changed_at,
        )
        run = FetchRunRecord(
            run_id=run_id,
            resource_id=resource_id,
            started_at=started_at,
            completed_at=completed_at,
            status=run_status,
            attempts=attempts,
            attempt_count=len(attempts),
            snapshot_id=snapshot.snapshot_id if snapshot is not None else None,
            error_code=error_code,
            error_message=error_message,
            retryable=retryable,
            http_status=http_status,
        )
        return await self._repository.record(
            AcquisitionRecord(resource=resource_record, snapshot=snapshot, run=run)
        )


def _validate_resource(source: KnowledgeSource, resource: DiscoveredResource) -> None:
    if resource.source_id != source.source_id:
        raise ValueError("resource source_id must match source")
    if resource.city != source.city:
        raise ValueError("resource city must match source")
    _validate_canonical_url(
        resource.url,
        allowed_domains=source.allowed_domains,
        field_name="resource URL",
    )
    if resource.url not in source.resource_urls:
        raise ValueError("resource URL must be registered for the source")


def _validate_canonical_url(
    value: object,
    *,
    allowed_domains: tuple[str, ...],
    field_name: str,
) -> None:
    url = _require_text(value, field_name)
    canonical = validate_source_url(url, allowed_domains=allowed_domains)
    if url != canonical:
        raise ValueError(f"{field_name} must be canonical")


def _validate_attempts(attempts: tuple[FetchAttempt, ...]) -> tuple[FetchAttempt, ...]:
    if not attempts:
        raise ValueError("execution must contain at least one attempt")
    previous_completed_at: datetime | None = None
    for expected_number, attempt in enumerate(attempts, start=1):
        if attempt.attempt_number != expected_number:
            raise ValueError("attempt numbers must be contiguous")
        started_at = _as_utc(attempt.started_at, "attempt started_at")
        completed_at = _as_utc(attempt.completed_at, "attempt completed_at")
        if completed_at < started_at:
            raise ValueError("attempt completed_at cannot precede started_at")
        if previous_completed_at is not None and started_at < previous_completed_at:
            raise ValueError("attempt timeline cannot overlap")
        previous_completed_at = completed_at
    return attempts


def _resource_id(source_id: str, source_url: str) -> ResourceId:
    return ResourceId(resource_id_for(source_id, source_url))


def _snapshot_id(
    resource_id: ResourceId,
    content_hash: str,
    parser_version: str,
) -> SnapshotId:
    digest = hashlib.sha256(
        f"{resource_id}\0{content_hash}\0{parser_version}".encode()
    ).hexdigest()
    return SnapshotId(digest)


def _require_text(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


def _optional_utc(value: datetime | None, field_name: str) -> datetime | None:
    if value is None:
        return None
    return _as_utc(value, field_name)


def _as_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _require_sha256(value: object, field_name: str) -> str:
    text = _require_text(value, field_name)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 hex digest")
    return text
