"""Optional LLM slot extraction — proposals only, never confirmed values.

Reuses the ``STRUCTURED_MODEL_*`` endpoint already configured for guide
extraction (no new credential surface).  Any failure — timeout, HTTP error,
schema mismatch — degrades to ``None`` so the deterministic wizard takes
over; the dialog loop never blocks on the model.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from trip_agent.providers.settings import structured_model_config

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "你是旅行规划助手的约束抽取器。只抽取用户消息中明确表达的约束，"
    "缺失的字段填 null，不得编造或猜测。budget_amount 是总预算（人民币元，整数）。"
    "destination 用城市名；start_date/end_date 归一化为 YYYY-MM-DD，"
    "年份缺失时取最近的未来日期。arrival_time/departure_time 用 24 小时制 HH:MM。"
    "preferences 只收主题标签（如亲子、美食、夜景、博物馆），每项不超过 6 个字。"
)

_EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "destination": {
            "type": ["string", "null"],
            "minLength": 2,
            "maxLength": 20,
        },
        "start_date": {
            "type": ["string", "null"],
            "description": "YYYY-MM-DD",
            "pattern": "^\\d{4}-\\d{2}-\\d{2}$",
        },
        "end_date": {
            "type": ["string", "null"],
            "description": "YYYY-MM-DD",
            "pattern": "^\\d{4}-\\d{2}-\\d{2}$",
        },
        "travelers": {"type": ["integer", "null"], "minimum": 1, "maximum": 20},
        "budget_amount": {
            "type": ["integer", "null"],
            "minimum": 100,
            "maximum": 1_000_000,
        },
        "pace": {
            "type": ["string", "null"],
            "enum": ["RELAXED", "BALANCED", "INTENSIVE", None],
        },
        "accommodation": {
            "type": ["string", "null"],
            "description": "酒店名或大概区域",
            "minLength": 2,
            "maxLength": 30,
        },
        "arrival_place": {"type": ["string", "null"], "minLength": 2, "maxLength": 30},
        "arrival_time": {
            "type": ["string", "null"],
            "description": "HH:MM 24小时制",
            "pattern": "^\\d{2}:\\d{2}$",
        },
        "departure_place": {"type": ["string", "null"], "minLength": 2, "maxLength": 30},
        "departure_time": {
            "type": ["string", "null"],
            "description": "HH:MM 24小时制",
            "pattern": "^\\d{2}:\\d{2}$",
        },
        "preferences": {
            "type": ["array", "null"],
            "items": {"type": "string", "minLength": 1, "maxLength": 12},
            "maxItems": 8,
        },
        "mobility": {
            "type": ["string", "null"],
            "enum": ["STANDARD", "REDUCED", "STEP_FREE", None],
        },
        "must_visit": {
            "type": ["array", "null"],
            "items": {"type": "string", "minLength": 1, "maxLength": 20},
            "maxItems": 8,
        },
        "avoid": {
            "type": ["array", "null"],
            "items": {"type": "string", "minLength": 1, "maxLength": 20},
            "maxItems": 8,
        },
    },
    "required": [
        "destination", "start_date", "end_date", "travelers", "budget_amount",
        "pace", "accommodation", "arrival_place", "arrival_time",
        "departure_place", "departure_time", "preferences", "mobility",
        "must_visit", "avoid",
    ],
    "additionalProperties": False,
}


class _ExtractionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    destination: str | None = Field(default=None, min_length=2, max_length=20)
    start_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    travelers: int | None = Field(default=None, ge=1, le=20)
    budget_amount: int | None = Field(default=None, ge=100, le=1_000_000)
    pace: Literal["RELAXED", "BALANCED", "INTENSIVE"] | None = None
    accommodation: str | None = Field(default=None, min_length=2, max_length=30)
    arrival_place: str | None = Field(default=None, min_length=2, max_length=30)
    arrival_time: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    departure_place: str | None = Field(default=None, min_length=2, max_length=30)
    departure_time: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    preferences: list[str] | None = Field(default=None, max_length=8)
    mobility: Literal["STANDARD", "REDUCED", "STEP_FREE"] | None = None
    must_visit: list[str] | None = Field(default=None, max_length=8)
    avoid: list[str] | None = Field(default=None, max_length=8)


class SlotExtractor:
    """Async slot extractor against an OpenAI-compatible endpoint."""

    def __init__(self, *, endpoint: str, api_key: str, model: str, timeout_seconds: float) -> None:
        self._endpoint = endpoint
        self._api_key = api_key
        self._model = model
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds, connect=3.0))

    async def extract(self, text: str) -> dict[str, Any] | None:
        """Return non-null proposed slots, or None on any failure."""
        try:
            response = await self._client.post(
                self._endpoint,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": self._model,
                    "messages": [
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": text[:2_000]},
                    ],
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {
                            "name": "trip_pilot_slot_extraction",
                            "strict": True,
                            "schema": _EXTRACTION_SCHEMA,
                        },
                    },
                },
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            payload = _ExtractionPayload.model_validate_json(str(content))
        except (
            httpx.HTTPError,
            ValidationError,
            json.JSONDecodeError,
            KeyError,
            TypeError,
            ValueError,
        ) as error:
            logger.warning("dialog_extraction_failed error=%s", type(error).__name__)
            return None
        slots = payload.model_dump(exclude_none=True)
        # merge place+time halves into whole anchors; drop partial ones
        merged: dict[str, Any] = {
            key: value for key, value in slots.items()
            if key not in ("arrival_place", "arrival_time", "departure_place", "departure_time")
        }
        for side in ("arrival", "departure"):
            place = slots.get(f"{side}_place")
            anchor_time = slots.get(f"{side}_time")
            if place and anchor_time:
                merged[side] = {"place": place, "time": anchor_time}
        return merged

    async def aclose(self) -> None:
        await self._client.aclose()


def build_extractor() -> SlotExtractor | None:
    shared = structured_model_config()
    if shared is None:
        return None
    return SlotExtractor(
        endpoint=shared.endpoint,
        api_key=shared.api_key,
        model=shared.model,
        timeout_seconds=shared.timeout_seconds,
    )
