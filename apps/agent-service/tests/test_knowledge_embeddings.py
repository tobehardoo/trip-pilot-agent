import asyncio
import json

import httpx
import pytest

from trip_agent.retrieval.embeddings import (
    DashScopeEmbeddingProvider,
    EmbeddingProviderError,
    HashEmbeddingProvider,
)


def test_hash_embedding_is_deterministic_normalized_and_dimensioned() -> None:
    provider = HashEmbeddingProvider(dimensions=32)

    first = asyncio.run(provider.embed_texts(("岭南文化", "本地美食")))
    second = asyncio.run(provider.embed_texts(("岭南文化", "本地美食")))

    assert first == second
    assert len(first) == 2
    assert all(len(vector.values) == 32 for vector in first)
    assert all(
        sum(value * value for value in vector.values) == pytest.approx(1.0) for vector in first
    )
    assert first[0] != first[1]
    assert provider.model_name == "demo-hash-v1"


def test_hash_embedding_rejects_empty_text_and_invalid_dimension() -> None:
    with pytest.raises(ValueError, match="dimensions"):
        HashEmbeddingProvider(dimensions=0)

    provider = HashEmbeddingProvider(dimensions=8)
    with pytest.raises(ValueError, match="empty"):
        asyncio.run(provider.embed_texts(("",)))


def test_hash_embedding_recovers_from_signed_hash_cancellation() -> None:
    vector = asyncio.run(HashEmbeddingProvider(dimensions=1).embed_texts(("a b",)))[0]

    assert vector.values == (1.0,)


def test_dashscope_embedding_uses_the_versioned_openai_compatible_contract() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL("https://dashscope.example/compatible-mode/v1/embeddings")
        assert request.headers["Authorization"] == "Bearer local-test-key"
        assert json.loads(request.content) == {
            "model": "text-embedding-v4",
            "input": ["岭南文化", "本地美食"],
            "dimensions": 3,
            "encoding_format": "float",
        }
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [0.4, 0.5, 0.6]},
                    {"index": 0, "embedding": [0.1, 0.2, 0.3]},
                ],
                "model": "text-embedding-v4",
            },
        )

    async def run_scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            provider = DashScopeEmbeddingProvider(
                api_key="local-test-key",
                base_url="https://dashscope.example/compatible-mode/v1",
                model_name="text-embedding-v4",
                dimensions=3,
                http_client=client,
            )
            return await provider.embed_texts(("岭南文化", "本地美食"))

    vectors = asyncio.run(run_scenario())

    assert tuple(vector.values for vector in vectors) == (
        (0.1, 0.2, 0.3),
        (0.4, 0.5, 0.6),
    )
    assert all(vector.model_name == "text-embedding-v4" for vector in vectors)


def test_dashscope_embedding_sanitizes_provider_failures_and_rejects_bad_dimensions() -> None:
    async def run_failure(response: httpx.Response) -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: response)
        ) as client:
            provider = DashScopeEmbeddingProvider(
                api_key="secret-key",
                base_url="https://dashscope.example/compatible-mode/v1",
                model_name="text-embedding-v4",
                dimensions=3,
                http_client=client,
            )
            with pytest.raises(EmbeddingProviderError) as raised:
                await provider.embed_texts(("广州",))
            assert "secret" not in str(raised.value)

    asyncio.run(
        run_failure(httpx.Response(401, json={"error": {"message": "secret-key invalid"}}))
    )
    asyncio.run(
        run_failure(
            httpx.Response(
                200,
                json={
                    "data": [{"index": 0, "embedding": [0.1, 0.2]}],
                    "model": "text-embedding-v4",
                },
            )
        )
    )
    asyncio.run(run_failure(httpx.Response(200, json=[])))
    asyncio.run(run_failure(httpx.Response(200, json={"data": ["invalid-item"]})))
