"""Bounded structured-model extraction that can only emit fact candidates."""

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from trip_agent.guide_intelligence.trusted_facts import (
    CandidateFact,
    NormalizedDocument,
    TrustedFactCategory,
    fact_ttl,
)
from trip_agent.providers.settings import structured_model_config


class StructuredModelTransport(Protocol):
    async def extract(
        self,
        *,
        content: str,
        json_schema: dict[str, object],
        timeout_seconds: float,
    ) -> object: ...


class _FactPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    category: TrustedFactCategory
    statement: str = Field(min_length=1, max_length=2_000)
    normalizedValue: dict[str, object]
    evidence: str = Field(min_length=1, max_length=2_000)
    evidenceStart: int = Field(ge=0)
    evidenceEnd: int = Field(gt=0)
    confidence: float = Field(ge=0, le=1)
    effectiveDate: str | None = None


class _ModelPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    facts: list[_FactPayload] = Field(max_length=100)


@dataclass(frozen=True, slots=True)
class ModelExtractionResult:
    status: Literal["EXTRACTED", "SKIPPED", "FAILED"]
    candidates: tuple[CandidateFact, ...]
    attempts: int
    failure_code: str | None = None
    failure_reason: str | None = None


class StructuredModelFactExtractor:
    """Use a strict output schema with bounded input, timeout, and retries."""

    def __init__(
        self,
        *,
        transport: StructuredModelTransport | None,
        timeout_seconds: float = 8.0,
        max_retries: int = 1,
        max_input_characters: int = 30_000,
    ) -> None:
        if not 0 < timeout_seconds <= 60:
            raise ValueError("timeout_seconds must be between zero and 60")
        if not 0 <= max_retries <= 3:
            raise ValueError("max_retries must be between zero and three")
        if not 1_000 <= max_input_characters <= 100_000:
            raise ValueError("max_input_characters must be between 1000 and 100000")
        self._transport = transport
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._max_input_characters = max_input_characters

    async def extract(
        self,
        document: NormalizedDocument,
        *,
        checked_at: datetime,
    ) -> ModelExtractionResult:
        if self._transport is None:
            return ModelExtractionResult(
                status="SKIPPED",
                candidates=(),
                attempts=0,
                failure_code="MODEL_NOT_CONFIGURED",
                failure_reason="structured model provider is not configured",
            )
        schema = _ModelPayload.model_json_schema()
        content = document.content[: self._max_input_characters]
        for attempt in range(1, self._max_retries + 2):
            try:
                raw_result = await self._transport.extract(
                    content=content,
                    json_schema=schema,
                    timeout_seconds=self._timeout_seconds,
                )
                payload = _parse_payload(raw_result)
                return ModelExtractionResult(
                    status="EXTRACTED",
                    candidates=tuple(
                        _candidate(item, checked_at=checked_at) for item in payload.facts
                    ),
                    attempts=attempt,
                )
            except TimeoutError as error:
                if attempt > self._max_retries:
                    return ModelExtractionResult(
                        status="FAILED",
                        candidates=(),
                        attempts=attempt,
                        failure_code="MODEL_TIMEOUT",
                        failure_reason=str(error) or "structured model request timed out",
                    )
            except (ValidationError, json.JSONDecodeError, TypeError, ValueError) as error:
                return ModelExtractionResult(
                    status="FAILED",
                    candidates=(),
                    attempts=attempt,
                    failure_code="MODEL_SCHEMA_INVALID",
                    failure_reason=str(error)[:1_000],
                )
            except httpx.TimeoutException as error:
                if attempt > self._max_retries:
                    return ModelExtractionResult(
                        status="FAILED",
                        candidates=(),
                        attempts=attempt,
                        failure_code="MODEL_TIMEOUT",
                        failure_reason=str(error)[:1_000],
                    )
            except httpx.HTTPError as error:
                if attempt > self._max_retries:
                    return ModelExtractionResult(
                        status="FAILED",
                        candidates=(),
                        attempts=attempt,
                        failure_code="MODEL_PROVIDER_FAILED",
                        failure_reason=type(error).__name__,
                    )
        raise AssertionError("bounded extraction loop exhausted unexpectedly")


class HttpStructuredModelTransport:
    """Call an OpenAI-compatible structured-output endpoint without logging secrets."""

    def __init__(
        self,
        *,
        endpoint: str,
        api_key: str,
        model: str,
        http_client: httpx.AsyncClient,
    ) -> None:
        if not endpoint.startswith("https://"):
            raise ValueError("structured model endpoint must use HTTPS")
        if not api_key.strip() or not model.strip():
            raise ValueError("structured model API key and model are required")
        self._endpoint = endpoint
        self._api_key = api_key
        self._model = model
        self._http_client = http_client

    async def extract(
        self,
        *,
        content: str,
        json_schema: dict[str, object],
        timeout_seconds: float,
    ) -> object:
        response = await self._http_client.post(
            self._endpoint,
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={
                "model": self._model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Extract only facts supported by an exact evidence span. "
                            "Do not infer missing facts."
                        ),
                    },
                    {"role": "user", "content": content},
                ],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "trip_pilot_fact_candidates",
                        "strict": True,
                        "schema": json_schema,
                    },
                },
            },
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        body = response.json()
        return body["choices"][0]["message"]["content"]


def configured_structured_extractor(
    http_client: httpx.AsyncClient,
) -> StructuredModelFactExtractor:
    shared = structured_model_config()
    if shared is None:
        return StructuredModelFactExtractor(transport=None)
    return StructuredModelFactExtractor(
        transport=HttpStructuredModelTransport(
            endpoint=shared.endpoint,
            api_key=shared.api_key,
            model=shared.model,
            http_client=http_client,
        ),
        timeout_seconds=shared.timeout_seconds,
        max_retries=shared.max_retries,
        max_input_characters=shared.max_input_characters,
    )


def _parse_payload(value: object) -> _ModelPayload:
    if isinstance(value, str):
        return _ModelPayload.model_validate_json(value)
    return TypeAdapter(_ModelPayload).validate_python(value, strict=True)


def _candidate(payload: _FactPayload, *, checked_at: datetime) -> CandidateFact:
    effective_date = (
        datetime.strptime(payload.effectiveDate, "%Y-%m-%d").date()
        if payload.effectiveDate is not None
        else None
    )
    return CandidateFact(
        category=payload.category,
        statement=payload.statement,
        normalized_value=payload.normalizedValue,
        evidence=payload.evidence,
        evidence_start=payload.evidenceStart,
        evidence_end=payload.evidenceEnd,
        confidence=payload.confidence,
        checked_at=checked_at,
        expires_at=checked_at + fact_ttl(payload.category),
        effective_date=effective_date,
    )
