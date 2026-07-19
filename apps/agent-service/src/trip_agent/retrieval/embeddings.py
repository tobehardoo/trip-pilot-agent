"""Embedding provider contracts and deterministic offline implementation."""

import hashlib
import math
import re
from typing import Annotated, Protocol

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

type EmbeddingModelName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]

_TOKEN_PATTERN = re.compile(r"[\u3400-\u9fff]|[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*")


class EmbeddingVector(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    values: tuple[float, ...] = Field(min_length=1)
    model_name: EmbeddingModelName

    @field_validator("values")
    @classmethod
    def require_finite_values(cls, values: tuple[float, ...]) -> tuple[float, ...]:
        if not all(math.isfinite(value) for value in values):
            raise ValueError("embedding values must be finite")
        return values


class EmbeddingProvider(Protocol):
    model_name: str
    dimensions: int

    async def embed_texts(self, texts: tuple[str, ...]) -> tuple[EmbeddingVector, ...]: ...


class HashEmbeddingProvider:
    """Feature-hash vectors for deterministic tests and offline demos."""

    model_name = "demo-hash-v1"

    def __init__(self, *, dimensions: int = 1024) -> None:
        if dimensions <= 0:
            raise ValueError("embedding dimensions must be positive")
        self.dimensions = dimensions

    async def embed_texts(self, texts: tuple[str, ...]) -> tuple[EmbeddingVector, ...]:
        return tuple(self._embed(text) for text in texts)

    def _embed(self, text: str) -> EmbeddingVector:
        tokens = _TOKEN_PATTERN.findall(text.casefold())
        if not tokens:
            raise ValueError("embedding text cannot be empty")

        values = [0.0] * self.dimensions
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:8], "big") % self.dimensions
            values[index] += -1.0 if digest[8] & 1 else 1.0

        norm = math.sqrt(sum(value * value for value in values))
        if norm == 0:
            fallback_digest = hashlib.sha256(text.encode("utf-8")).digest()
            values[int.from_bytes(fallback_digest[:8], "big") % self.dimensions] = 1.0
            norm = 1.0
        normalized = tuple(value / norm for value in values)
        return EmbeddingVector(values=normalized, model_name=self.model_name)
