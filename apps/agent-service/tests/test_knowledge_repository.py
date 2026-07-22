import asyncio
import os
from collections.abc import Iterator
from textwrap import dedent

import psycopg
import pytest

from trip_agent.retrieval.documents import parse_markdown_document
from trip_agent.retrieval.embeddings import HashEmbeddingProvider
from trip_agent.retrieval.repository import (
    KnowledgeSearchRequest,
    KnowledgeVersionConflict,
    PsycopgKnowledgeRepository,
)
from trip_agent.retrieval.service import KnowledgeImporter

MARKDOWN = dedent(
    """
    +++
    document_id = "guangzhou-shamian-rag"
    city = "广州"
    category = "culture"
    title = "沙面岛与岭南文化"
    source_url = "https://example.com/guangzhou/shamian"
    source_name = "广州文旅"
    collected_at = "2026-07-19T08:00:00+08:00"
    reliability_level = "CURATED"
    version = 1
    applicable_seasons = ["all"]
    +++

    # 沙面岛

    沙面岛适合安排城市漫步，沿途观察岭南文化与近代建筑。
    """
).strip()


def database_url() -> str:
    value = os.environ.get("KNOWLEDGE_TEST_DATABASE_URL", "").strip()
    if not value:
        pytest.skip("KNOWLEDGE_TEST_DATABASE_URL is not configured")
    return value


@pytest.fixture(autouse=True)
def reset_knowledge_tables() -> Iterator[None]:
    url = database_url()
    asyncio.run(PsycopgKnowledgeRepository(url).migrate())
    with psycopg.connect(url) as connection:
        connection.execute(
            "TRUNCATE agent.knowledge_chunk_embedding, agent.knowledge_chunk, "
            "agent.knowledge_document RESTART IDENTITY CASCADE"
        )
    yield


def test_repository_is_idempotent_and_rejects_same_version_changes() -> None:
    repository = PsycopgKnowledgeRepository(database_url())
    provider = HashEmbeddingProvider(dimensions=32)
    importer = KnowledgeImporter(repository=repository, embedding_provider=provider)

    asyncio.run(repository.migrate())
    first = asyncio.run(importer.import_markdown(MARKDOWN))
    second = asyncio.run(importer.import_markdown(MARKDOWN))

    assert first.status == "created"
    assert second.status == "unchanged"

    changed = parse_markdown_document(MARKDOWN.replace("近代建筑", "骑楼建筑"))
    with pytest.raises(KnowledgeVersionConflict):
        asyncio.run(importer.import_document(changed))

    changed_metadata = parse_markdown_document(
        MARKDOWN.replace('title = "沙面岛与岭南文化"', 'title = "沙面历史文化"')
    )
    with pytest.raises(KnowledgeVersionConflict):
        asyncio.run(importer.import_document(changed_metadata))


def test_concurrent_same_version_imports_are_idempotent() -> None:
    async def import_concurrently():
        importers = tuple(
            KnowledgeImporter(
                repository=PsycopgKnowledgeRepository(database_url()),
                embedding_provider=HashEmbeddingProvider(dimensions=32),
            )
            for _ in range(10)
        )
        return await asyncio.gather(
            *(importer.import_markdown(MARKDOWN) for importer in importers)
        )

    results = asyncio.run(import_concurrently())

    assert [result.status for result in results].count("created") == 1
    assert [result.status for result in results].count("unchanged") == 9


def test_repository_adds_embeddings_without_replacing_source_version() -> None:
    repository = PsycopgKnowledgeRepository(database_url())
    first_importer = KnowledgeImporter(
        repository=repository,
        embedding_provider=HashEmbeddingProvider(dimensions=32),
    )
    second_provider = HashEmbeddingProvider(dimensions=64)
    second_importer = KnowledgeImporter(
        repository=repository,
        embedding_provider=second_provider,
    )

    assert asyncio.run(first_importer.import_markdown(MARKDOWN)).status == "created"
    assert asyncio.run(second_importer.import_markdown(MARKDOWN)).status == "embedded"
    assert asyncio.run(second_importer.import_markdown(MARKDOWN)).status == "unchanged"

    query_vector = asyncio.run(second_provider.embed_texts(("沙面岛 岭南文化",)))[0]
    results = asyncio.run(
        repository.search(KnowledgeSearchRequest(city="广州", embedding=query_vector))
    )
    assert results
    assert all(result.document_version == 1 for result in results)


def test_repository_search_applies_city_and_similarity_filters() -> None:
    repository = PsycopgKnowledgeRepository(database_url())
    provider = HashEmbeddingProvider(dimensions=32)
    importer = KnowledgeImporter(repository=repository, embedding_provider=provider)
    asyncio.run(repository.migrate())
    asyncio.run(importer.import_markdown(MARKDOWN))
    query_vector = asyncio.run(provider.embed_texts(("沙面岛 岭南文化",)))[0]

    results = asyncio.run(
        repository.search(
            KnowledgeSearchRequest(
                city="广州",
                embedding=query_vector,
                limit=5,
                min_similarity=0.1,
            )
        )
    )
    wrong_city = asyncio.run(
        repository.search(
            KnowledgeSearchRequest(
                city="杭州",
                embedding=query_vector,
                limit=5,
            )
        )
    )

    assert results
    assert results[0].title == "沙面岛与岭南文化"
    assert results[0].similarity >= 0.1
    assert wrong_city == ()


def test_repository_search_returns_only_latest_valid_version() -> None:
    repository = PsycopgKnowledgeRepository(database_url())
    provider = HashEmbeddingProvider(dimensions=32)
    importer = KnowledgeImporter(repository=repository, embedding_provider=provider)
    version_two = MARKDOWN.replace("version = 1", "version = 2").replace(
        "沙面岛适合安排城市漫步，沿途观察岭南文化与近代建筑。",
        "沙面岛新版资料强调历史街区保护和步行体验。",
    )
    asyncio.run(importer.import_markdown(MARKDOWN))
    asyncio.run(importer.import_markdown(version_two))
    query_vector = asyncio.run(provider.embed_texts(("沙面岛",)))[0]

    results = asyncio.run(
        repository.search(
            KnowledgeSearchRequest(
                city="广州",
                embedding=query_vector,
                limit=50,
                min_similarity=-1,
            )
        )
    )

    assert results
    assert {result.document_version for result in results} == {2}
