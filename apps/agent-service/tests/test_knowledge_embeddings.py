import asyncio

import pytest

from trip_agent.retrieval.embeddings import HashEmbeddingProvider


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
