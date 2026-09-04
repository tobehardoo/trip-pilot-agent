"""Knowledge citation -> planning guide-fact bridge (pre-planning injection)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from trip_agent.retrieval.governance import FRESH_WINDOW_DAYS
from trip_agent.retrieval.planning_bridge import (
    _guide_fact_id,
    _guide_import_id,
    inject_knowledge_guide_facts,
    knowledge_citation_to_guide_fact,
)
from trip_agent.retrieval.repository import KnowledgeCitation

COLLECTED = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)


def _citation(reliability: str) -> KnowledgeCitation:
    return KnowledgeCitation(
        chunk_id="chunk-1",
        document_id="doc-1",
        document_version=1,
        chunk_index=0,
        city="广州",
        category="poi",
        title="标题：推荐值得到访",
        content="内容提到 Alpha、珠江夜游、值得一逛",
        source_url="https://example.com/post",
        source_name="小红书作者",
        reliability_level=reliability,
        claim_type="RECOMMENDATION",
        collected_at=COLLECTED,
        similarity=0.8,
    )


class TestKnowledgeCitationToGuideFact:
    def test_community_maps_to_ugc_source_and_tip_category(self) -> None:
        fact = knowledge_citation_to_guide_fact(_citation("COMMUNITY"))
        assert fact is not None
        assert fact.source_type == "XIAOHONGSHU_SHARED_TEXT"
        assert fact.category == "TIP"
        assert fact.confidence == 0.8

    def test_official_maps_to_official_tourism(self) -> None:
        fact = knowledge_citation_to_guide_fact(_citation("OFFICIAL"))
        assert fact is not None
        assert fact.source_type == "OFFICIAL_TOURISM"

    def test_unknown_reliability_is_rejected(self) -> None:
        fact = knowledge_citation_to_guide_fact(_citation("UNKNOWN"))
        assert fact is None

    def test_freshness_window_becomes_expiry_bound(self) -> None:
        fact = knowledge_citation_to_guide_fact(_citation("CURATED"))
        assert fact is not None
        assert fact.observed_at == COLLECTED
        assert fact.expires_at == COLLECTED + timedelta(days=FRESH_WINDOW_DAYS)

    def test_deterministic_uuids(self) -> None:
        fact = knowledge_citation_to_guide_fact(_citation("COMMUNITY"))
        assert fact is not None
        assert fact.fact_id == _guide_fact_id("chunk-1")
        assert fact.guide_import_id == _guide_import_id("doc-1")


class TestInjectKnowledgeGuideFacts:
    def test_none_or_non_real_leaves_command_unchanged(self) -> None:
        # No command needed to verify the early-return guard: use a stub.
        class Stubcommand:
            pass

        stub = Stubcommand()
        assert inject_knowledge_guide_facts(stub, None) is stub  # type: ignore[arg-type]
        assert inject_knowledge_guide_facts(stub, object()) is stub  # type: ignore[arg-type]