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
            result = service.import_text(
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
    )


def _require_internal_token(provided: str | None) -> None:
    expected = os.getenv("AGENT_INTERNAL_TOKEN", "")
    if not expected or provided is None or not hmac.compare_digest(provided, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid internal service token")
