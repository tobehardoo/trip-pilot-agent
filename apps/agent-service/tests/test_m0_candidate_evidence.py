"""M0 L3: candidate ranking tiers guide-match by reliability x freshness."""

from datetime import UTC, datetime, timedelta

from trip_agent.guide_intelligence.trusted_facts import ValidatedFact
from trip_agent.planning.candidates import CandidateRanker
from trip_agent.providers.map import Coordinates, Poi

NOW = datetime(2026, 9, 1, tzinfo=UTC)


def poi(provider_id: str, name: str) -> Poi:
    return Poi(
        provider_id=provider_id,
        name=name,
        coordinates=Coordinates(longitude=113.26, latitude=23.13),
        type_name="风景名胜",
        type_code="110000",
        province="广东省",
        city="广州市",
        district="越秀区",
        address="广州市越秀区",
    )


def guide_fact(
    *,
    fact_id: str,
    entity: str,
    statement: str,
    reliability: str,
    collected_at: datetime,
) -> ValidatedFact:
    return ValidatedFact(
        fact_id=fact_id,
        document_id=f"doc-{fact_id}",
        category="ATTRACTION",
        statement=statement,
        normalized_value={"poiName": entity},
        evidence=statement,
        evidence_start=0,
        evidence_end=len(statement),
        confidence=0.9,
        checked_at=collected_at,
        expires_at=collected_at + timedelta(days=7),
        effective_date=None,
        source_type="ACQUIRED",
        source_name=reliability,
        source_url=None,
        reliability_level=reliability,
        source_reviewed=False,
        hard_constraint_eligible=False,
        entity=entity,
        source_id="test-source",
    )


def test_official_recent_guide_fact_outranks_ocr_stale() -> None:
    museum_a = poi("a", "越秀博物馆")
    museum_b = poi("b", "越秀艺术馆")
    facts = (
        guide_fact(
            fact_id="gov-fresh",
            entity="越秀博物馆",
            statement="越秀博物馆值得一去，人少方便。",
            reliability="OFFICIAL_GOV",
            collected_at=NOW - timedelta(days=3),
        ),
        guide_fact(
            fact_id="ocr-stale",
            entity="越秀艺术馆",
            statement="越秀艺术馆值得一看。",
            reliability="OCR_UNVERIFIED",
            collected_at=NOW - timedelta(days=200),
        ),
    )

    result = CandidateRanker().rank(
        (museum_a, museum_b),
        destination="广州",
        preferences=(),
        traveler_type="SOLO",
        limit=2,
        evidence_facts=facts,
        evidence_now=NOW,
    )

    by_id = {item.poi.provider_id: item for item in result.selected}
    a_score = by_id["a"].score
    b_score = by_id["b"].score
    # OFFICIAL_GOV + fresh is strictly higher than stale OCR (>= 20 gap).
    assert a_score - b_score >= 20
    assert any(r == "GUIDE_FACT_MATCH:OFFICIAL_GOV" for r in by_id["a"].reasons)
    # Stale OCR yields a zero tiered bonus (base score only, no extra points).
    assert b_score == 20


def test_flat_guide_statement_boost_unchanged_without_evidence_facts() -> None:
    museum = poi("a", "越秀博物馆")
    result = CandidateRanker().rank(
        (museum,),
        destination="广州",
        preferences=(),
        traveler_type="SOLO",
        limit=1,
        guide_statements=("越秀博物馆值得一去。",),
    )

    item = result.selected[0]
    assert item.score == 20 + 25
    assert "GUIDE_FACT_MATCH" in item.reasons