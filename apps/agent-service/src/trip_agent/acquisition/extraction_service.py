"""Batch application service for immutable snapshot extraction results."""

import asyncio
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from typing import Literal, Protocol

from trip_agent.acquisition.extraction import (
    ArticleExtractionResult,
    ExtractionQualityIssue,
    GuangzhouGovernmentArticleExtractor,
)

type ExtractionPersistenceStatus = Literal["created", "unchanged"]


class ExtractionVersionConflict(ValueError):
    """Raised when an immutable snapshot/parser result changes."""


@dataclass(frozen=True, slots=True)
class PendingSnapshot:
    snapshot_id: str
    raw_content: bytes
    content_type: str | None
    fetched_at: datetime


@dataclass(frozen=True, slots=True)
class SnapshotExtractionRecord:
    extraction_id: str
    snapshot_id: str
    parser_version: str
    status: Literal["EXTRACTED", "REJECTED"]
    title: str | None
    content: str | None
    content_hash: str | None
    published_at: datetime | None
    content_source: str | None
    issues: tuple[ExtractionQualityIssue, ...]
    result_fingerprint: str
    extracted_at: datetime

    def __post_init__(self) -> None:
        normalized_published_at = _optional_utc(self.published_at, "published_at")
        object.__setattr__(self, "published_at", normalized_published_at)
        expected_id = hashlib.sha256(
            f"{self.snapshot_id}\0{self.parser_version}".encode()
        ).hexdigest()
        if self.extraction_id != expected_id:
            raise ValueError("extraction_id does not match snapshot and parser")
        if self.status == "EXTRACTED":
            if self.title is None or self.content is None or self.content_hash is None:
                raise ValueError("EXTRACTED record requires article content")
            if any(issue.severity == "ERROR" for issue in self.issues):
                raise ValueError("EXTRACTED record cannot contain ERROR issues")
            if self.content_hash != hashlib.sha256(self.content.encode()).hexdigest():
                raise ValueError("content_hash does not match extracted content")
        else:
            if not any(issue.severity == "ERROR" for issue in self.issues):
                raise ValueError("REJECTED record requires an ERROR issue")
            if any(
                value is not None
                for value in (
                    self.title,
                    self.content,
                    self.content_hash,
                    self.published_at,
                    self.content_source,
                )
            ):
                raise ValueError("REJECTED record cannot contain article content")
        expected_fingerprint = _result_fingerprint(
            status=self.status,
            parser_version=self.parser_version,
            title=self.title,
            content=self.content,
            content_hash=self.content_hash,
            published_at=self.published_at,
            content_source=self.content_source,
            issues=self.issues,
        )
        if self.result_fingerprint != expected_fingerprint:
            raise ValueError("result_fingerprint does not match extraction result")
        _as_utc(self.extracted_at)


@dataclass(frozen=True, slots=True)
class ExtractionPersisted:
    extraction_id: str
    snapshot_id: str
    status: ExtractionPersistenceStatus


@dataclass(frozen=True, slots=True)
class SnapshotExtractionProcessed:
    snapshot_id: str
    extraction_status: Literal["EXTRACTED", "REJECTED"]
    persistence: ExtractionPersisted


class SnapshotExtractionRepository(Protocol):
    async def list_snapshots_pending_extraction(
        self,
        *,
        parser_version: str,
        limit: int,
    ) -> tuple[PendingSnapshot, ...]: ...

    async def save_extraction(self, record: SnapshotExtractionRecord) -> ExtractionPersisted: ...


class ArticleExtractor(Protocol):
    parser_version: str

    def extract(
        self,
        *,
        content: bytes,
        content_type: str | None,
        fetched_at: datetime,
    ) -> ArticleExtractionResult: ...


class SnapshotExtractionService:
    def __init__(
        self,
        *,
        repository: SnapshotExtractionRepository,
        extractor: ArticleExtractor | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._extractor = extractor or GuangzhouGovernmentArticleExtractor()
        self._clock = clock or _utc_now

    @property
    def parser_version(self) -> str:
        return self._extractor.parser_version

    async def process_pending(
        self,
        *,
        limit: int = 20,
    ) -> tuple[SnapshotExtractionProcessed, ...]:
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        snapshots = await self._repository.list_snapshots_pending_extraction(
            parser_version=self.parser_version,
            limit=limit,
        )
        processed: list[SnapshotExtractionProcessed] = []
        for snapshot in snapshots:
            result = await asyncio.to_thread(
                partial(
                    self._extractor.extract,
                    content=snapshot.raw_content,
                    content_type=snapshot.content_type,
                    fetched_at=snapshot.fetched_at,
                )
            )
            record = self.build_record(snapshot=snapshot, result=result)
            persistence = await self._repository.save_extraction(record)
            processed.append(
                SnapshotExtractionProcessed(
                    snapshot_id=snapshot.snapshot_id,
                    extraction_status=result.status,
                    persistence=persistence,
                )
            )
        return tuple(processed)

    def build_record(
        self,
        *,
        snapshot: PendingSnapshot,
        result: ArticleExtractionResult,
    ) -> SnapshotExtractionRecord:
        parser_version = (
            result.article.parser_version
            if result.status == "EXTRACTED"
            else result.parser_version
        )
        if parser_version != self.parser_version:
            raise ValueError("extraction result parser version must match extractor")
        if result.status == "EXTRACTED":
            article = result.article
            title = article.title
            content = article.content
            content_hash = hashlib.sha256(content.encode()).hexdigest()
            published_at = _optional_utc(article.published_at, "published_at")
            content_source = article.content_source
        else:
            title = content = content_hash = published_at = content_source = None
        fingerprint = _result_fingerprint(
            status=result.status,
            parser_version=parser_version,
            title=title,
            content=content,
            content_hash=content_hash,
            published_at=published_at,
            content_source=content_source,
            issues=result.issues,
        )
        extraction_id = hashlib.sha256(
            f"{snapshot.snapshot_id}\0{parser_version}".encode()
        ).hexdigest()
        return SnapshotExtractionRecord(
            extraction_id=extraction_id,
            snapshot_id=snapshot.snapshot_id,
            parser_version=parser_version,
            status=result.status,
            title=title,
            content=content,
            content_hash=content_hash,
            published_at=published_at,
            content_source=content_source,
            issues=result.issues,
            result_fingerprint=fingerprint,
            extracted_at=_as_utc(self._clock()),
        )


def _result_fingerprint(
    *,
    status: Literal["EXTRACTED", "REJECTED"],
    parser_version: str,
    title: str | None,
    content: str | None,
    content_hash: str | None,
    published_at: datetime | None,
    content_source: str | None,
    issues: tuple[ExtractionQualityIssue, ...],
) -> str:
    payload = {
            "status": status,
            "parser_version": parser_version,
            "title": title,
            "content": content,
            "content_hash": content_hash,
            "published_at": published_at.isoformat() if published_at else None,
            "content_source": content_source,
            "issues": [
                {"code": issue.code, "severity": issue.severity, "message": issue.message}
                for issue in issues
            ],
        }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("extraction clock must return a timezone-aware datetime")
    return value.astimezone(UTC)


def _optional_utc(value: datetime | None, field_name: str) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _utc_now() -> datetime:
    return datetime.now(UTC)
