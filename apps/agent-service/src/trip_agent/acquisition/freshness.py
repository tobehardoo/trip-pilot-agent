"""Operational freshness reporting for configured acquisition resources."""

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol

from trip_agent.acquisition.models import KnowledgeSource, resource_id_for
from trip_agent.acquisition.registry import SourceCatalog

type FetchRunStatus = Literal["FETCHED", "NOT_MODIFIED", "FAILED"]
type FreshnessStatus = Literal["FRESH", "STALE"]
type StaleReason = Literal[
    "NEVER_ATTEMPTED",
    "NEVER_VERIFIED",
    "VERIFICATION_OVERDUE",
    "IDENTITY_MISMATCH",
]


@dataclass(frozen=True, slots=True)
class ResourceFreshnessState:
    resource_id: str
    source_id: str
    source_url: str
    last_attempted_at: datetime
    last_verified_at: datetime | None
    last_changed_at: datetime | None
    latest_run_status: FetchRunStatus | None
    latest_error_code: str | None
    latest_error_message: str | None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "last_attempted_at",
            _as_utc(self.last_attempted_at, "last_attempted_at"),
        )
        object.__setattr__(
            self,
            "last_verified_at",
            _optional_utc(self.last_verified_at, "last_verified_at"),
        )
        object.__setattr__(
            self,
            "last_changed_at",
            _optional_utc(self.last_changed_at, "last_changed_at"),
        )
        if self.latest_run_status == "FAILED":
            if self.latest_error_code is None or self.latest_error_message is None:
                raise ValueError("FAILED latest run requires error details")
        elif self.latest_error_code is not None or self.latest_error_message is not None:
            raise ValueError("non-failed latest run cannot contain error details")


@dataclass(frozen=True, slots=True)
class ResourceFreshness:
    resource_id: str
    source_url: str
    status: FreshnessStatus
    stale_reason: StaleReason | None
    last_attempted_at: datetime | None
    latest_run_status: FetchRunStatus | None
    latest_error_code: str | None
    latest_error_message: str | None
    last_verified_at: datetime | None
    last_changed_at: datetime | None
    verification_due_at: datetime | None


@dataclass(frozen=True, slots=True)
class SourceFreshness:
    source_id: str
    source_name: str
    city: str
    status: FreshnessStatus
    fetch_interval_hours: int
    resource_count: int
    stale_resource_count: int
    resources: tuple[ResourceFreshness, ...]


@dataclass(frozen=True, slots=True)
class FreshnessReport:
    generated_at: datetime
    status: FreshnessStatus
    source_count: int
    resource_count: int
    stale_resource_count: int
    sources: tuple[SourceFreshness, ...]


class FreshnessRepository(Protocol):
    async def list_resource_freshness(self) -> tuple[ResourceFreshnessState, ...]: ...


class FreshnessReportService:
    def __init__(
        self,
        *,
        repository: FreshnessRepository,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._clock = clock or _utc_now

    async def generate(self, catalog: SourceCatalog) -> FreshnessReport:
        generated_at = _as_utc(self._clock(), "freshness clock")
        states = await self._repository.list_resource_freshness()
        state_by_resource = {state.resource_id: state for state in states}
        sources = tuple(
            self._source_report(
                source=source,
                generated_at=generated_at,
                states=state_by_resource,
            )
            for source in sorted(catalog.sources, key=lambda item: item.source_id)
        )
        resource_count = sum(source.resource_count for source in sources)
        stale_count = sum(source.stale_resource_count for source in sources)
        return FreshnessReport(
            generated_at=generated_at,
            status="STALE" if stale_count else "FRESH",
            source_count=len(sources),
            resource_count=resource_count,
            stale_resource_count=stale_count,
            sources=sources,
        )

    @staticmethod
    def _source_report(
        *,
        source: KnowledgeSource,
        generated_at: datetime,
        states: dict[str, ResourceFreshnessState],
    ) -> SourceFreshness:
        resources = tuple(
            _resource_report(
                source_id=source.source_id,
                source_url=source_url,
                interval=timedelta(hours=source.fetch_interval_hours),
                generated_at=generated_at,
                state=states.get(resource_id_for(source.source_id, source_url)),
            )
            for source_url in source.resource_urls
        )
        stale_count = sum(resource.status == "STALE" for resource in resources)
        return SourceFreshness(
            source_id=source.source_id,
            source_name=source.source_name,
            city=source.city,
            status="STALE" if stale_count else "FRESH",
            fetch_interval_hours=source.fetch_interval_hours,
            resource_count=len(resources),
            stale_resource_count=stale_count,
            resources=resources,
        )


def render_freshness_report(report: FreshnessReport) -> str:
    return json.dumps(
        asdict(report),
        ensure_ascii=False,
        indent=2,
        default=_json_default,
    )


def _resource_report(
    *,
    source_id: str,
    source_url: str,
    interval: timedelta,
    generated_at: datetime,
    state: ResourceFreshnessState | None,
) -> ResourceFreshness:
    if state is None:
        return _unverified_resource(source_id, source_url, "NEVER_ATTEMPTED")
    if state.source_id != source_id or state.source_url != source_url:
        return _unverified_resource(source_id, source_url, "IDENTITY_MISMATCH")
    due_at = state.last_verified_at + interval if state.last_verified_at else None
    if state.last_verified_at is None:
        status: FreshnessStatus = "STALE"
        reason: StaleReason | None = "NEVER_VERIFIED"
    elif due_at is not None and generated_at >= due_at:
        status = "STALE"
        reason = "VERIFICATION_OVERDUE"
    else:
        status = "FRESH"
        reason = None
    return ResourceFreshness(
        resource_id=state.resource_id,
        source_url=source_url,
        status=status,
        stale_reason=reason,
        last_attempted_at=state.last_attempted_at,
        latest_run_status=state.latest_run_status,
        latest_error_code=state.latest_error_code,
        latest_error_message=state.latest_error_message,
        last_verified_at=state.last_verified_at,
        last_changed_at=state.last_changed_at,
        verification_due_at=due_at,
    )


def _unverified_resource(
    source_id: str,
    source_url: str,
    reason: Literal["NEVER_ATTEMPTED", "IDENTITY_MISMATCH"],
) -> ResourceFreshness:
    return ResourceFreshness(
        resource_id=resource_id_for(source_id, source_url),
        source_url=source_url,
        status="STALE",
        stale_reason=reason,
        last_attempted_at=None,
        latest_run_status=None,
        latest_error_code=None,
        latest_error_message=None,
        last_verified_at=None,
        last_changed_at=None,
        verification_due_at=None,
    )


def _json_default(value: object) -> str:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    raise TypeError(f"unsupported freshness JSON value: {type(value).__name__}")


def _as_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must return a timezone-aware datetime")
    return value.astimezone(UTC)


def _optional_utc(value: datetime | None, field_name: str) -> datetime | None:
    if value is None:
        return None
    return _as_utc(value, field_name)


def _utc_now() -> datetime:
    return datetime.now(UTC)
