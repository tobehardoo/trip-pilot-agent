"""Embedding provider contracts and deterministic offline implementation."""

import hashlib
import math
import re
from typing import Annotated, Protocol
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

type EmbeddingModelName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]

_TOKEN_PATTERN = re.compile(r"[\u3400-\u9fff]|[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*")


class EmbeddingProviderError(RuntimeError):
    """A sanitized model-provider failure safe for application boundaries."""


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


class DashScopeEmbeddingProvider:
    """DashScope text embedding v4 through its OpenAI-compatible HTTP API."""

    _max_batch_size = 10

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model_name: str = "text-embedding-v4",
        dimensions: int = 1024,
        timeout_seconds: float = 10.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        parsed_url = urlsplit(base_url)
        if parsed_url.scheme != "https" or not parsed_url.hostname:
            raise ValueError("DashScope base URL must be an HTTPS URL")
        if parsed_url.username is not None or parsed_url.password is not None:
            raise ValueError("DashScope base URL must not contain credentials")
        if not api_key.strip():
            raise ValueError("DashScope API key cannot be empty")
        if not model_name.strip() or len(model_name.strip()) > 100:
            raise ValueError("DashScope embedding model name is invalid")
        if dimensions <= 0:
            raise ValueError("DashScope embedding dimensions must be positive")
        if not 0 < timeout_seconds <= 60:
            raise ValueError("DashScope embedding timeout must be between 0 and 60 seconds")
        self._api_key = api_key.strip()
        self._base_url = base_url.rstrip("/")
        self.model_name = model_name.strip()
        self.dimensions = dimensions
        self._timeout_seconds = timeout_seconds
        self._http_client = http_client

    async def embed_texts(self, texts: tuple[str, ...]) -> tuple[EmbeddingVector, ...]:
        if not texts:
            return ()
        if any(not text.strip() for text in texts):
            raise ValueError("embedding text cannot be empty")
        if self._http_client is not None:
            return await self._embed_batches(self._http_client, texts)
        async with httpx.AsyncClient(timeout=self._timeout_seconds, trust_env=False) as client:
            return await self._embed_batches(client, texts)

    async def _embed_batches(
        self,
        client: httpx.AsyncClient,
        texts: tuple[str, ...],
    ) -> tuple[EmbeddingVector, ...]:
        vectors: list[EmbeddingVector] = []
        for start in range(0, len(texts), self._max_batch_size):
            batch = texts[start:start + self._max_batch_size]
            vectors.extend(await self._embed_batch(client, batch))
        return tuple(vectors)

    async def _embed_batch(
        self,
        client: httpx.AsyncClient,
        texts: tuple[str, ...],
    ) -> tuple[EmbeddingVector, ...]:
        try:
            response = await client.post(
                f"{self._base_url}/embeddings",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": self.model_name,
                    "input": list(texts),
                    "dimensions": self.dimensions,
                    "encoding_format": "float",
                },
                timeout=self._timeout_seconds,
            )
            if response.status_code < 200 or response.status_code >= 300:
                raise EmbeddingProviderError("DashScope embedding request failed")
            payload = response.json()
            if not isinstance(payload, dict):
                raise EmbeddingProviderError("DashScope embedding response is incompatible")
            data = payload.get("data")
            if payload.get("model") != self.model_name or not isinstance(data, list):
                raise EmbeddingProviderError("DashScope embedding response is incompatible")
            if not all(isinstance(item, dict) for item in data):
                raise EmbeddingProviderError("DashScope embedding response is incompatible")
            indexed = sorted(data, key=lambda item: item["index"])
            if [item["index"] for item in indexed] != list(range(len(texts))):
                raise EmbeddingProviderError(
                    "DashScope embedding response indexes are incompatible"
                )
            vectors = tuple(
                EmbeddingVector(
                    values=tuple(item["embedding"]),
                    model_name=self.model_name,
                )
                for item in indexed
            )
            if any(len(vector.values) != self.dimensions for vector in vectors):
                raise EmbeddingProviderError(
                    "DashScope embedding response dimensions are incompatible"
                )
            return vectors
        except EmbeddingProviderError:
            raise
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
            raise EmbeddingProviderError("DashScope embedding request failed") from error
