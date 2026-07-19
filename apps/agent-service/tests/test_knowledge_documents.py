from datetime import UTC, datetime
from pathlib import Path
from textwrap import dedent

import pytest
from pydantic import ValidationError

from trip_agent.retrieval.documents import (
    chunk_document,
    parse_markdown_document,
)

MARKDOWN = dedent(
    """
    +++
    document_id = "guangzhou-shamian-culture"
    city = "广州"
    category = "culture"
    title = "沙面岛岭南建筑"
    source_url = "https://example.com/guangzhou/shamian"
    source_name = "广州文旅"
    collected_at = "2026-07-19T08:00:00+08:00"
    reliability_level = "OFFICIAL"
    version = 1
    applicable_seasons = ["all"]
    traveler_types = ["FAMILY", "COUPLE"]
    +++

    # 沙面岛

    沙面保留了连续的近代建筑群，适合安排城市漫步和岭南文化观察。

    ## 行程建议

    清晨和傍晚光线较柔和，亲子游客可以把步行距离拆成两段。
    """
).strip()


def test_parse_markdown_document_validates_metadata_and_hashes_body() -> None:
    document = parse_markdown_document(MARKDOWN)

    assert document.document_id == "guangzhou-shamian-culture"
    assert document.city == "广州"
    assert document.category == "culture"
    assert document.title == "沙面岛岭南建筑"
    assert document.source_name == "广州文旅"
    assert document.collected_at == datetime(2026, 7, 19, 0, 0, tzinfo=UTC)
    assert document.content_hash == parse_markdown_document(MARKDOWN).content_hash
    assert (
        document.content_hash
        != parse_markdown_document(MARKDOWN.replace("城市漫步", "城市观察")).content_hash
    )


def test_parser_rejects_missing_front_matter_and_invalid_reliability() -> None:
    with pytest.raises(ValueError, match="front matter"):
        parse_markdown_document("# 没有元数据\n\n内容")

    invalid = MARKDOWN.replace('reliability_level = "OFFICIAL"', 'reliability_level = "UNKNOWN"')
    with pytest.raises(ValidationError):
        parse_markdown_document(invalid)


def test_chunking_is_stable_and_keeps_heading_context() -> None:
    document = parse_markdown_document(MARKDOWN)

    chunks = chunk_document(document, max_characters=64, overlap_characters=8)

    assert len(chunks) >= 2
    assert chunks == chunk_document(document, max_characters=64, overlap_characters=8)
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    assert all(len(chunk.content) <= 64 for chunk in chunks)
    assert all(chunk.document_id == document.document_id for chunk in chunks)
    assert all(chunk.token_count > 0 for chunk in chunks)
    assert any("沙面岛" in chunk.content for chunk in chunks)
    assert any("行程建议" in chunk.content for chunk in chunks)


@pytest.mark.parametrize(
    ("max_characters", "overlap_characters"),
    [(0, 2), (20, 20), (20, 21)],
)
def test_chunking_rejects_invalid_window(max_characters: int, overlap_characters: int) -> None:
    document = parse_markdown_document(MARKDOWN)

    with pytest.raises(ValueError):
        chunk_document(
            document,
            max_characters=max_characters,
            overlap_characters=overlap_characters,
        )


def test_repository_guangzhou_documents_are_valid_and_uniquely_versioned() -> None:
    knowledge_directory = Path(__file__).parents[3] / "knowledge" / "guangzhou"
    paths = tuple(sorted(knowledge_directory.glob("*.md")))

    documents = tuple(parse_markdown_document(path.read_text(encoding="utf-8")) for path in paths)

    assert len(documents) >= 3
    identities = {(document.document_id, document.version) for document in documents}
    assert len(identities) == len(documents)
    assert all(document.city == "广州" for document in documents)
    assert all(
        str(document.source_url).startswith("https://www.gz.gov.cn/") for document in documents
    )
