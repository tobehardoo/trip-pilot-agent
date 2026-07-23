"""Internal HTTP contract for guide intelligence extraction."""

import hmac
import os
from datetime import datetime

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, Field

from trip_agent.acquisition.fetch_models import AcquisitionFetchError
from trip_agent.acquisition.security import SourceSecurityError
from trip_agent.guide_intelligence.service import GuideImportService

router = APIRouter(prefix="/internal/v1", tags=["guide-intelligence"])


class GuideImportRequest(BaseModel):
    sourceUrl: str = Field(min_length=1, max_length=2048)


class TravelFactResponse(BaseModel):
    category: str
    statement: str
    evidence: str
    confidence: float
    observed_at: datetime = Field(alias="observedAt")
    expires_at: datetime = Field(alias="expiresAt")


class GuideImportResponse(BaseModel):
    source_url: str = Field(alias="sourceUrl")
    final_url: str = Field(alias="finalUrl")
    source_host: str = Field(alias="sourceHost")
    title: str
    excerpt: str
    content_hash: str = Field(alias="contentHash")
    fetched_at: datetime = Field(alias="fetchedAt")
    facts: list[TravelFactResponse]


@router.post("/guide-imports", response_model=GuideImportResponse)
async def import_guide(
    request: GuideImportRequest,
    x_internal_token: str | None = Header(default=None),
) -> GuideImportResponse:
    _require_internal_token(x_internal_token)
    try:
        result = await GuideImportService().import_url(request.sourceUrl)
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
    return GuideImportResponse(
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
                observedAt=fact.observed_at,
                expiresAt=fact.expires_at,
            )
            for fact in result.facts
        ],
    )


def _require_internal_token(provided: str | None) -> None:
    expected = os.getenv("AGENT_INTERNAL_TOKEN", "")
    if not expected or provided is None or not hmac.compare_digest(provided, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid internal service token")
