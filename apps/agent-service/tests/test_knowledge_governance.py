"""Governance + per-document freshness eligibility (retrieval -> planning gate)."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta

from trip_agent.retrieval.governance import (
    FRESH_WINDOW_DAYS,
    assess_document,
    claim_allowed,
    maximally_permissive_claim_type,
)
from trip_agent.retrieval.repository import KnowledgeCitation
from trip_agent.worker.knowledge import GovernedKnowledgeFreshnessProvider

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
COLLECTED_FRESH = NOW - timedelta(days=10)
COLLECTED_STALE = NOW - timedelta(days=FRESH_WINDOW_DAYS + 5)


def _citation(
    *,
    reliability: str,
    claim_type: str,
    collected: datetime,
) -> KnowledgeCitation:
    return KnowledgeCitation(
        chunk_id="c0",
        document_id="doc-1",
        document_version=1,
        chunk_index=0,
        city="广州",
        category="poi",
        title="t",
        content="内容",
        source_url="https://example.com/a",
        source_name="来源",
        reliability_level=reliability,
        claim_type=claim_type,
        collected_at=collected,
        similarity=0.7,
    )


class TestClaimTypePolicy:
    def test_community_never_allowed_for_factual_attribute(self) -> None:
        assert claim_allowed("FACTUAL_ATTRIBUTE", "COMMUNITY") is False
        assert claim_allowed("FACTUAL_ATTRIBUTE", "CURATED") is False
        assert claim_allowed("FACTUAL_ATTRIBUTE", "OFFICIAL") is True

    def test_all_reliabilities_may_recommend(self) -> None:
        for reliability in ("OFFICIAL", "CURATED", "COMMUNITY"):
            assert claim_allowed("RECOMMENDATION", reliability) is True

    def test_default_claim_maps_to_allowed_scope(self) -> None:
        assert maximally_permissive_claim_type("OFFICIAL") == "FACTUAL_ATTRIBUTE"
        assert maximally_permissive_claim_type("COMMUNITY") == "RECOMMENDATION"


class TestAssessDocument:
    def test_official_fresh_factual_is_usable(self) -> None:
        v = assess_document(
            claim_type="FACTUAL_ATTRIBUTE",
            reliability="OFFICIAL",
            collected_at=COLLECTED_FRESH,
            now=NOW,
        )
        assert v.usable is True and v.fresh is True

    def test_stale_official_factual_is_excluded(self) -> None:
        v = assess_document(
            claim_type="FACTUAL_ATTRIBUTE",
            reliability="OFFICIAL",
            collected_at=COLLECTED_STALE,
            now=NOW,
        )
        assert v.usable is False
        assert v.stale_reason == "STALE_FACTUAL_SOURCE"

    def test_expired_document_excluded(self) -> None:
        v = assess_document(
            claim_type="RECOMMENDATION",
            reliability="CURATED",
            collected_at=COLLECTED_FRESH,
            valid_to=date(2026, 8, 1),
            now=NOW,
        )
        assert v.usable is False
        assert v.stale_reason == "DOCUMENT_VALIDITY_EXPIRED"

    def test_stale_community_recommendation_is_soft_not_hard_blocked(self) -> None:
        v = assess_document(
            claim_type="RECOMMENDATION",
            reliability="COMMUNITY",
            collected_at=COLLECTED_STALE,
            now=NOW,
        )
        # Still usable (soft signal — ranking will penalise the staleness) —
        # but it IS flagged as not fresh.
        assert v.usable is True
        assert v.fresh is False


class TestGovernedKnowledgeFreshnessProvider:
    def test_empty_citations_unavailable(self) -> None:
        p = GovernedKnowledgeFreshnessProvider(clock=lambda: NOW)
        assert asyncio.run(p.assess("广州", ())).status == "UNAVAILABLE"

    def test_community_recommendation_eligible_fresh(self) -> None:
        p = GovernedKnowledgeFreshnessProvider(clock=lambda: NOW)
        result = asyncio.run(
            p.assess(
                "广州",
                (
                    _citation(
                        reliability="COMMUNITY",
                        claim_type="RECOMMENDATION",
                        collected=COLLECTED_FRESH,
                    ),
                ),
            )
        )
        assert result.status == "FRESH"

    def test_all_stale_community_returns_stale_but_passes(self) -> None:
        p = GovernedKnowledgeFreshnessProvider(clock=lambda: NOW)
        result = asyncio.run(
            p.assess(
                "广州",
                (
                    _citation(
                        reliability="CURATED",
                        claim_type="RECOMMENDATION",
                        collected=COLLECTED_STALE,
                    ),
                ),
            )
        )
        assert result.status == "STALE"

    def test_community_factual_attribute_is_not_eligible(self) -> None:
        p = GovernedKnowledgeFreshnessProvider(clock=lambda: NOW)
        result = asyncio.run(
            p.assess(
                "广州",
                (
                    _citation(
                        reliability="COMMUNITY",
                        claim_type="FACTUAL_ATTRIBUTE",
                        collected=COLLECTED_FRESH,
                    ),
                ),
            )
        )
        assert result.status == "UNAVAILABLE"