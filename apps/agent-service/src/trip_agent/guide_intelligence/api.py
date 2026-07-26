"""Internal HTTP contract for guide intelligence extraction."""

import hmac
import os
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, Field, model_validator

from trip_agent.acquisition.fetch_models import AcquisitionFetchError
from trip_agent.acquisition.security import SourceSecurityError
from trip_agent.guide_intelligence.service import GuideImportService

router = APIRouter(prefix="/internal/v1", tags=["guide-intelligence"])


class GuideImportRequest(BaseModel):
    sourceUrl: str | None = Field(default=None, min_length=1, max_length=2048)
    sourceType: Literal[
        "PUBLIC_GUIDE_URL",
        "PASTED_TEXT",
        "TEXT_FILE",
        "XIAOHONGSHU_SHARED_TEXT",
        "CITY_INTELLIGENCE",
    ] = "PUBLIC_GUIDE_URL"
    title: str | None = Field(default=None, min_length=1, max_length=300)
    content: str | None = Field(default=None, min_length=1, max_length=100_000)
    city: str | None = Field(default=None, min_length=1, max_length=60)
    startDate: date | None = None
    endDate: date | None = None

    @model_validator(mode="after")
    def validate_source(self) -> "GuideImportRequest":
        has_url = self.sourceUrl is not None and bool(self.sourceUrl.strip())
        has_content = self.content is not None and bool(self.content.strip())
        has_city = self.city is not None and bool(self.city.strip())
        if sum((has_url, has_content, has_city)) != 1:
            raise ValueError("provide exactly one of sourceUrl, content, or city")
        if has_url and self.sourceType != "PUBLIC_GUIDE_URL":
            raise ValueError("sourceUrl requires PUBLIC_GUIDE_URL sourceType")
        if has_content and (
            self.sourceType == "PUBLIC_GUIDE_URL"
            or self.title is None
            or not self.title.strip()
        ):
            raise ValueError("text imports require sourceType and title")
        if has_city and (
            self.sourceType != "CITY_INTELLIGENCE"
            or self.startDate is None
            or self.endDate is None
            or self.endDate < self.startDate
        ):
            raise ValueError("city intelligence requires a valid city and date range")
        return self


class TravelFactResponse(BaseModel):
    category: str
    statement: str
    evidence: str
    confidence: float
    effective_date: date | None = Field(default=None, alias="effectiveDate")
    observed_at: datetime = Field(alias="observedAt")
    expires_at: datetime = Field(alias="expiresAt")


class GuideImportResponse(BaseModel):
    source_type: str = Field(alias="sourceType")
    source_url: str = Field(alias="sourceUrl")
    final_url: str = Field(alias="finalUrl")
    source_host: str = Field(alias="sourceHost")
    title: str
    excerpt: str
    content_hash: str = Field(alias="contentHash")
    fetched_at: datetime = Field(alias="fetchedAt")
    facts: list[TravelFactResponse]
    normalized_document: "NormalizedDocumentResponse | None" = Field(
        default=None,
        alias="normalizedDocument",
    )
    trusted_facts: list["TrustedFactResponse"] = Field(
        default_factory=list,
        alias="trustedFacts",
    )
    rejected_facts: list["RejectedFactResponse"] = Field(
        default_factory=list,
        alias="rejectedFacts",
    )
    merge_decisions: list["MergeDecisionResponse"] = Field(
        default_factory=list,
        alias="factMergeDecisions",
    )
    model_extraction: "ModelExtractionResponse" = Field(alias="modelExtraction")


class NormalizedDocumentResponse(BaseModel):
    document_id: str = Field(alias="documentId")
    source_type: str = Field(alias="sourceType")
    source_name: str = Field(alias="sourceName")
    source_url: str | None = Field(alias="sourceUrl")
    city: str
    title: str
    content: str
    fetched_at: datetime = Field(alias="fetchedAt")
    content_hash: str = Field(alias="contentHash")
    encoding: str
    language: str
    metadata: dict[str, object]
    reliability_level: str = Field(alias="reliabilityLevel")
    source_reviewed: bool = Field(alias="sourceReviewed")


class TrustedFactResponse(BaseModel):
    fact_id: str = Field(alias="factId")
    document_id: str = Field(alias="documentId")
    category: str
    statement: str
    normalized_value: dict[str, object] = Field(alias="normalizedValue")
    evidence: str
    evidence_start: int = Field(alias="evidenceStart")
    evidence_end: int = Field(alias="evidenceEnd")
    confidence: float
    checked_at: datetime = Field(alias="checkedAt")
    expires_at: datetime = Field(alias="expiresAt")
    effective_date: date | None = Field(alias="effectiveDate")
    source_type: str = Field(alias="sourceType")
    source_name: str = Field(alias="sourceName")
    source_url: str | None = Field(alias="sourceUrl")
    reliability_level: str = Field(alias="reliabilityLevel")
    source_reviewed: bool = Field(alias="sourceReviewed")
    hard_constraint_eligible: bool = Field(alias="hardConstraintEligible")


class RejectionReasonResponse(BaseModel):
    code: str
    message: str


class RejectedFactResponse(BaseModel):
    category: str
    statement: str
    reasons: list[RejectionReasonResponse]


class MergeDecisionResponse(BaseModel):
    selected_fact_id: str = Field(alias="selectedFactId")
    conflict_fact_ids: list[str] = Field(alias="conflictFactIds")
    downgraded_fact_ids: list[str] = Field(alias="downgradedFactIds")
    reason: str
    needs_manual_review: bool = Field(alias="needsManualReview")


class ModelExtractionResponse(BaseModel):
    status: str
    attempts: int
    failure_code: str | None = Field(alias="failureCode")
    failure_reason: str | None = Field(alias="failureReason")


@router.post("/guide-imports", response_model=GuideImportResponse)
async def import_guide(
    request: GuideImportRequest,
    x_internal_token: str | None = Header(default=None),
) -> GuideImportResponse:
    _require_internal_token(x_internal_token)
    try:
        service = GuideImportService()
        if request.sourceType == "CITY_INTELLIGENCE":
            if request.city is None or request.startDate is None or request.endDate is None:
                raise ValueError("city intelligence requires city and dates")
            result = await service.import_city(
                city=request.city,
                start_date=request.startDate,
                end_date=request.endDate,
            )
        elif request.sourceUrl is not None:
            result = await service.import_url(request.sourceUrl)
        else:
            if request.title is None or request.content is None:
                raise ValueError("text imports require title and content")
            result = await service.import_text_with_model(
                source_type=request.sourceType,
                title=request.title,
                content=request.content,
            )
    except SourceSecurityError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(error)) from error
    except ValueError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(error)) from error
    except AcquisitionFetchError as error:
        response_status = (
            status.HTTP_422_UNPROCESSABLE_ENTITY
            if not error.retryable
            else status.HTTP_502_BAD_GATEWAY
        )
        raise HTTPException(response_status, f"{error.code}: {error}") from error
    except RuntimeError as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(error)) from error
    return GuideImportResponse(
        sourceType=result.source_type,
        sourceUrl=result.source_url,
        finalUrl=result.final_url,
        sourceHost=result.source_host,
        title=result.title,
        excerpt=result.excerpt,
        contentHash=result.content_hash,
        fetchedAt=result.fetched_at,
        facts=[
            TravelFactResponse(
                category=fact.category,
                statement=fact.statement,
                evidence=fact.evidence,
                confidence=fact.confidence,
                effectiveDate=fact.effective_date,
                observedAt=fact.observed_at,
                expiresAt=fact.expires_at,
            )
            for fact in result.facts
        ],
        normalizedDocument=(
            NormalizedDocumentResponse(
                documentId=result.normalized_document.document_id,
                sourceType=result.normalized_document.source_type,
                sourceName=result.normalized_document.source_name,
                sourceUrl=result.normalized_document.source_url,
                city=result.normalized_document.city,
                title=result.normalized_document.title,
                content=result.normalized_document.content,
                fetchedAt=result.normalized_document.fetched_at,
                contentHash=result.normalized_document.content_hash,
                encoding=result.normalized_document.encoding,
                language=result.normalized_document.language,
                metadata=dict(result.normalized_document.metadata),
                reliabilityLevel=result.normalized_document.reliability_level,
                sourceReviewed=result.normalized_document.source_reviewed,
            )
            if result.normalized_document is not None
            else None
        ),
        trustedFacts=[
            TrustedFactResponse(
                factId=fact.fact_id,
                documentId=fact.document_id,
                category=fact.category,
                statement=fact.statement,
                normalizedValue=dict(fact.normalized_value),
                evidence=fact.evidence,
                evidenceStart=fact.evidence_start,
                evidenceEnd=fact.evidence_end,
                confidence=fact.confidence,
                checkedAt=fact.checked_at,
                expiresAt=fact.expires_at,
                effectiveDate=fact.effective_date,
                sourceType=fact.source_type,
                sourceName=fact.source_name,
                sourceUrl=fact.source_url,
                reliabilityLevel=fact.reliability_level,
                sourceReviewed=fact.source_reviewed,
                hardConstraintEligible=fact.hard_constraint_eligible,
            )
            for fact in result.trusted_facts
        ],
        rejectedFacts=[
            RejectedFactResponse(
                category=rejected.candidate.category,
                statement=rejected.candidate.statement,
                reasons=[
                    RejectionReasonResponse(code=reason.code, message=reason.message)
                    for reason in rejected.reasons
                ],
            )
            for rejected in result.rejected_facts
        ],
        factMergeDecisions=[
            MergeDecisionResponse(
                selectedFactId=decision.selected_fact.fact_id,
                conflictFactIds=[
                    fact.fact_id for fact in decision.conflict_facts
                ],
                downgradedFactIds=[
                    fact.fact_id for fact in decision.downgraded_facts
                ],
                reason=decision.reason,
                needsManualReview=decision.needs_manual_review,
            )
            for decision in result.merge_decisions
        ],
        modelExtraction=ModelExtractionResponse(
            status=result.model_extraction.status,
            attempts=result.model_extraction.attempts,
            failureCode=result.model_extraction.failure_code,
            failureReason=result.model_extraction.failure_reason,
        ),
    )


def _require_internal_token(provided: str | None) -> None:
    expected = os.getenv("AGENT_INTERNAL_TOKEN", "")
    if not expected or provided is None or not hmac.compare_digest(provided, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid internal service token")
