"""Human review and the sole publication boundary for acquired knowledge."""

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Literal, Protocol
from zoneinfo import ZoneInfo

from trip_agent.acquisition.extraction import ExtractionQualityIssue
from trip_agent.retrieval.documents import (
    ApplicableSeason,
    KnowledgeCategory,
    KnowledgeDocument,
    ReliabilityLevel,
    TravelerType,
)
from trip_agent.retrieval.service import ImportStatus, KnowledgeImportResult

type ReviewActionType = Literal["APPROVE", "REJECT", "WITHDRAW"]
type ReviewStatus = Literal["APPROVED", "REJECTED", "WITHDRAWN"]
type ReviewPersistenceStatus = Literal["created", "unchanged"]

_HEX_ID = re.compile(r"^[0-9a-f]{64}$")
_CATEGORIES = {"accommodation", "culture", "food", "poi", "season", "theme", "travel_tip"}
_SEASONS = {"all", "spring", "summer", "autumn", "winter"}
_TRAVELER_TYPES = {"SOLO", "COUPLE", "FAMILY", "FRIENDS", "BUSINESS"}


class ReviewStateConflict(ValueError):
    """Raised when a candidate cannot accept the requested review transition."""


class PublicationNotAvailable(ValueError):
    """Raised when an approval is absent, withdrawn, or currently claimed."""


@dataclass(frozen=True, slots=True)
class ReviewApprovalRequest:
    extraction_id: str
    reviewer_id: str
    note: str
    category: KnowledgeCategory
    valid_from: date | None = None
    valid_to: date | None = None
    applicable_seasons: tuple[ApplicableSeason, ...] = ()
    traveler_types: tuple[TravelerType, ...] = ()

    def __post_init__(self) -> None:
        _require_hex_id(self.extraction_id, "extraction_id")
        object.__setattr__(self, "reviewer_id", _require_text(self.reviewer_id, "reviewer_id", 200))
        object.__setattr__(self, "note", _require_text(self.note, "note", 2_000))
        if self.category not in _CATEGORIES:
            raise ValueError(f"unsupported knowledge category: {self.category}")
        if self.valid_from and self.valid_to and self.valid_from > self.valid_to:
            raise ValueError("valid_from cannot be after valid_to")
        _validate_unique_values(
            self.applicable_seasons,
            field_name="applicable_seasons",
            allowed=_SEASONS,
        )
        _validate_unique_values(
            self.traveler_types,
            field_name="traveler_types",
            allowed=_TRAVELER_TYPES,
        )


@dataclass(frozen=True, slots=True)
class ReviewRejectionRequest:
    extraction_id: str
    reviewer_id: str
    note: str

    def __post_init__(self) -> None:
        _require_hex_id(self.extraction_id, "extraction_id")
        object.__setattr__(self, "reviewer_id", _require_text(self.reviewer_id, "reviewer_id", 200))
        object.__setattr__(self, "note", _require_text(self.note, "note", 2_000))


@dataclass(frozen=True, slots=True)
class ReviewWithdrawalRequest:
    approval_action_id: str
    reviewer_id: str
    note: str

    def __post_init__(self) -> None:
        _require_hex_id(self.approval_action_id, "approval_action_id")
        object.__setattr__(self, "reviewer_id", _require_text(self.reviewer_id, "reviewer_id", 200))
        object.__setattr__(self, "note", _require_text(self.note, "note", 2_000))


@dataclass(frozen=True, slots=True)
class ReviewAction:
    action_id: str
    decision_fingerprint: str
    action: ReviewActionType
    reviewer_id: str
    note: str
    reviewed_at: datetime
    extraction_id: str | None = None
    parent_action_id: str | None = None
    category: KnowledgeCategory | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    applicable_seasons: tuple[ApplicableSeason, ...] = ()
    traveler_types: tuple[TravelerType, ...] = ()


@dataclass(frozen=True, slots=True)
class ReviewPersistence:
    action_id: str
    snapshot_id: str
    review_status: ReviewStatus
    persistence_status: ReviewPersistenceStatus
    document_id: str | None = None
    document_version: int | None = None


@dataclass(frozen=True, slots=True)
class PendingReviewCandidate:
    extraction_id: str
    snapshot_id: str
    city: str
    source_url: str
    source_name: str
    title: str
    content: str
    published_at: datetime | None
    fetched_at: datetime
    extracted_at: datetime
    quality_issues: tuple[ExtractionQualityIssue, ...]


class ReviewRepository(Protocol):
    async def list_reviews_pending(
        self,
        *,
        limit: int,
    ) -> tuple[PendingReviewCandidate, ...]: ...

    async def save_review_action(self, action: ReviewAction) -> ReviewPersistence: ...


class KnowledgeReviewService:
    def __init__(
        self,
        *,
        repository: ReviewRepository,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._clock = clock or _utc_now

    async def list_pending(self, *, limit: int = 20) -> tuple[PendingReviewCandidate, ...]:
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        return await self._repository.list_reviews_pending(limit=limit)

    async def approve(self, request: ReviewApprovalRequest) -> ReviewPersistence:
        return await self._repository.save_review_action(
            _build_action(
                action="APPROVE",
                reviewer_id=request.reviewer_id,
                note=request.note,
                reviewed_at=_as_utc(self._clock(), "review clock"),
                extraction_id=request.extraction_id,
                category=request.category,
                valid_from=request.valid_from,
                valid_to=request.valid_to,
                applicable_seasons=request.applicable_seasons,
                traveler_types=request.traveler_types,
            )
        )

    async def reject(self, request: ReviewRejectionRequest) -> ReviewPersistence:
        return await self._repository.save_review_action(
            _build_action(
                action="REJECT",
                reviewer_id=request.reviewer_id,
                note=request.note,
                reviewed_at=_as_utc(self._clock(), "review clock"),
                extraction_id=request.extraction_id,
            )
        )

    async def withdraw(self, request: ReviewWithdrawalRequest) -> ReviewPersistence:
        return await self._repository.save_review_action(
            _build_action(
                action="WITHDRAW",
                reviewer_id=request.reviewer_id,
                note=request.note,
                reviewed_at=_as_utc(self._clock(), "review clock"),
                parent_action_id=request.approval_action_id,
            )
        )


@dataclass(frozen=True, slots=True)
class PublicationClaim:
    review_action_id: str
    claim_token: int
    document_id: str
    document_version: int
    city: str
    category: KnowledgeCategory
    title: str
    content: str
    content_hash: str
    source_url: str
    source_name: str
    reliability_level: ReliabilityLevel
    published_at: datetime | None
    collected_at: datetime
    valid_from: date | None
    valid_to: date | None
    applicable_seasons: tuple[ApplicableSeason, ...]
    traveler_types: tuple[TravelerType, ...]


@dataclass(frozen=True, slots=True)
class PublishedKnowledge:
    review_action_id: str
    document_id: str
    document_version: int
    chunk_count: int
    importer_status: ImportStatus


type PublicationClaimResult = PublicationClaim | PublishedKnowledge | None


class ReviewPublicationRepository(Protocol):
    async def claim_publication(
        self,
        *,
        review_action_id: str,
        claim_timeout: timedelta,
    ) -> PublicationClaimResult: ...

    async def mark_publication_succeeded(
        self,
        *,
        review_action_id: str,
        claim_token: int,
        result: KnowledgeImportResult,
        published_at: datetime,
    ) -> None: ...

    async def mark_publication_failed(
        self,
        *,
        review_action_id: str,
        claim_token: int,
        error: str,
        failed_at: datetime,
    ) -> None: ...


class KnowledgeDocumentImporter(Protocol):
    async def import_document(self, document: KnowledgeDocument) -> KnowledgeImportResult: ...


class KnowledgeReviewPublisher:
    """The only acquisition adapter allowed to publish into the RAG importer."""

    def __init__(
        self,
        *,
        repository: ReviewPublicationRepository,
        importer: KnowledgeDocumentImporter,
        clock: Callable[[], datetime] | None = None,
        claim_timeout: timedelta = timedelta(minutes=15),
        publication_timezone: str = "Asia/Shanghai",
    ) -> None:
        if claim_timeout <= timedelta(0):
            raise ValueError("claim_timeout must be positive")
        self._repository = repository
        self._importer = importer
        self._clock = clock or _utc_now
        self._claim_timeout = claim_timeout
        self._publication_timezone = ZoneInfo(publication_timezone)

    async def publish(self, review_action_id: str) -> KnowledgeImportResult:
        _require_hex_id(review_action_id, "review_action_id")
        claimed = await self._repository.claim_publication(
            review_action_id=review_action_id,
            claim_timeout=self._claim_timeout,
        )
        if claimed is None:
            raise PublicationNotAvailable(
                f"review action {review_action_id} is not available for publication"
            )
        if isinstance(claimed, PublishedKnowledge):
            return KnowledgeImportResult(
                document_id=claimed.document_id,
                version=claimed.document_version,
                chunk_count=claimed.chunk_count,
                status=claimed.importer_status,
            )

        document = self._to_document(claimed)
        try:
            result = await self._importer.import_document(document)
        except Exception as error:
            try:
                await self._repository.mark_publication_failed(
                    review_action_id=review_action_id,
                    claim_token=claimed.claim_token,
                    error=f"{type(error).__name__}: {error}",
                    failed_at=_as_utc(self._clock(), "publication clock"),
                )
            except Exception as audit_error:
                error.add_note(f"failed to persist publication failure: {audit_error}")
            raise
        await self._repository.mark_publication_succeeded(
            review_action_id=review_action_id,
            claim_token=claimed.claim_token,
            result=result,
            published_at=_as_utc(self._clock(), "publication clock"),
        )
        return result

    def _to_document(self, claim: PublicationClaim) -> KnowledgeDocument:
        published_at = (
            claim.published_at.astimezone(self._publication_timezone).date()
            if claim.published_at
            else None
        )
        return KnowledgeDocument(
            document_id=claim.document_id,
            city=claim.city,
            category=claim.category,
            title=claim.title,
            content=claim.content,
            content_hash=claim.content_hash,
            source_url=claim.source_url,
            source_name=claim.source_name,
            published_at=published_at,
            collected_at=claim.collected_at,
            valid_from=claim.valid_from,
            valid_to=claim.valid_to,
            applicable_seasons=claim.applicable_seasons,
            traveler_types=claim.traveler_types,
            reliability_level=claim.reliability_level,
            version=claim.document_version,
        )


def _build_action(
    *,
    action: ReviewActionType,
    reviewer_id: str,
    note: str,
    reviewed_at: datetime,
    extraction_id: str | None = None,
    parent_action_id: str | None = None,
    category: KnowledgeCategory | None = None,
    valid_from: date | None = None,
    valid_to: date | None = None,
    applicable_seasons: tuple[ApplicableSeason, ...] = (),
    traveler_types: tuple[TravelerType, ...] = (),
) -> ReviewAction:
    payload = {
        "action": action,
        "reviewer_id": reviewer_id,
        "note": note,
        "extraction_id": extraction_id,
        "parent_action_id": parent_action_id,
        "category": category,
        "valid_from": valid_from.isoformat() if valid_from else None,
        "valid_to": valid_to.isoformat() if valid_to else None,
        "applicable_seasons": applicable_seasons,
        "traveler_types": traveler_types,
    }
    fingerprint = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    action_id = hashlib.sha256(f"trip-pilot:review:{fingerprint}".encode()).hexdigest()
    return ReviewAction(
        action_id=action_id,
        decision_fingerprint=fingerprint,
        action=action,
        reviewer_id=reviewer_id,
        note=note,
        reviewed_at=reviewed_at,
        extraction_id=extraction_id,
        parent_action_id=parent_action_id,
        category=category,
        valid_from=valid_from,
        valid_to=valid_to,
        applicable_seasons=applicable_seasons,
        traveler_types=traveler_types,
    )


def _require_hex_id(value: str, field_name: str) -> None:
    if not isinstance(value, str) or _HEX_ID.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a 64-character lowercase hex value")


def _require_text(value: str, field_name: str, max_length: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    if len(normalized) > max_length:
        raise ValueError(f"{field_name} cannot exceed {max_length} characters")
    return normalized


def _validate_unique_values(
    values: tuple[str, ...],
    *,
    field_name: str,
    allowed: set[str],
) -> None:
    if not isinstance(values, tuple):
        raise ValueError(f"{field_name} must be a tuple")
    if len(values) != len(set(values)):
        raise ValueError(f"{field_name} must be unique")
    unsupported = set(values) - allowed
    if unsupported:
        raise ValueError(f"unsupported {field_name}: {sorted(unsupported)}")


def _as_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must return a timezone-aware datetime")
    return value.astimezone(UTC)


def _utc_now() -> datetime:
    return datetime.now(UTC)
