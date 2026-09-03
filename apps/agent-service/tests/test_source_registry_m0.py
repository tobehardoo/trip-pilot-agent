"""M0 second trusted source: offline closure source-registry -> L0 -> L1 -> scoring."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from trip_agent.acquisition.source_registry import SourceRegistry, discover_resources
from trip_agent.guide_intelligence.evidence_fusion import fuse_facts
from trip_agent.guide_intelligence.trusted_facts import ValidatedFact
from trip_agent.planning.candidates import CandidateRanker
from trip_agent.providers.map import Coordinates, Poi

KNOWLEDGE_ROOT = Path(__file__).parents[3] / "knowledge"
NOW = datetime(2026, 9, 1, tzinfo=UTC)
PUBLIC_SOURCE_ID = "guangzhou-government-tourism"
SECOND_SOURCE_ID = "guangzhou-culture-open-data"


def _registry() -> SourceRegistry:
    return SourceRegistry.load(KNOWLEDGE_ROOT / "sources")


def test_guangzhou_has_a_second_trusted_source() -> None:
    registry = _registry()

    sources = registry.sources_for_city("广州")
    ids = [s.source_id for s in sources]

    assert SECOND_SOURCE_ID in ids
    second = registry.source_by_id(SECOND_SOURCE_ID)
    assert second is not None
    assert second.reliability_level == "CURATED"
    assert registry.reliability_for(SECOND_SOURCE_ID) == "CURATED"


def test_second_source_resources_are_fetcher_ready_and_unique() -> None:
    registry = _registry()
    second = registry.source_by_id(SECOND_SOURCE_ID)
    assert second is not None

    resources = discover_resources(second)
    first = registry.source_by_id(PUBLIC_SOURCE_ID)
    assert first is not None

    assert len(resources) == 2
    # wire-compatible with HttpResourceFetcher.fetch(source=..., resource=...)
    for resource in resources:
        assert resource.source_id == SECOND_SOURCE_ID
        assert resource.city == "广州"
        assert resource.url.startswith("https://data.gz.gov.cn/")
    assert len({r.url for r in discover_resources(first)} | {r.url for r in resources}) > 0


def _make_fact(
    *,
    fact_id: str,
    reliability: str,
    source_id: str,
    collected_at: datetime,
) -> ValidatedFact:
    return ValidatedFact(
        fact_id=fact_id,
        document_id=f"doc-{fact_id}",
        category="ATTRACTION",
        statement="陈家祠值得一游，门票免费。",
        normalized_value={"poiName": "陈家祠"},
        evidence="陈家祠值得一游，门票免费。",
        evidence_start=0,
        evidence_end=14,
        confidence=0.9,
        checked_at=collected_at,
        expires_at=collected_at + timedelta(days=7),
        effective_date=None,
        source_type="ACQUIRED",
        source_name=source_id,
        source_url=None,
        reliability_level=reliability,
        source_reviewed=True,
        hard_constraint_eligible=False,
        entity="陈家祠",
        source_id=source_id,
    )


def test_second_source_to_l1_to_scoring_closure_offline() -> None:
    """Second source -> L0 facts -> L1 fuse -> L3 scoring, offline."""
    registry = _registry()
    public = registry.source_by_id(PUBLIC_SOURCE_ID)
    second = registry.source_by_id(SECOND_SOURCE_ID)
    assert public is not None and second is not None

    facts = (
        _make_fact(
            fact_id="fact-public",
            reliability=public.reliability_level,  # OFFICIAL
            source_id=public.source_id,
            collected_at=NOW - timedelta(days=5),
        ),
        _make_fact(
            fact_id="fact-second",
            reliability=second.reliability_level,  # CURATED
            source_id=second.source_id,
            collected_at=NOW - timedelta(days=1),
        ),
    )

    conclusions = fuse_facts(facts)

    assert len(conclusions) == 1
    conclusion = conclusions[0]
    assert conclusion.status == "VERIFIED"
    assert len(conclusion.sources) == 2
    assert {s.source_id for s in conclusion.sources} == {PUBLIC_SOURCE_ID, SECOND_SOURCE_ID}

    # L3: the fused evidence boosts the matching POI.
    chen = Poi(
        provider_id="chen",
        name="陈家祠",
        coordinates=Coordinates(longitude=113.26, latitude=23.13),
        type_name="名胜古迹",
        type_code="110000",
        province="广东省",
        city="广州市",
        district="越秀区",
        address="广州市越秀区",
    )
    other = Poi(
        provider_id="other",
        name="其他地点",
        coordinates=Coordinates(longitude=113.26, latitude=23.13),
        type_name="风景名胜",
        type_code="110000",
        province="广东省",
        city="广州市",
        district="越秀区",
        address="广州市越秀区",
    )
    result = CandidateRanker().rank(
        (chen, other),
        destination="广州",
        preferences=(),
        traveler_type="SOLO",
        limit=2,
        evidence_facts=facts,
        evidence_now=NOW,
    )
    by_id = {item.poi.provider_id: item for item in result.selected}
    assert any(r.startswith("GUIDE_FACT_MATCH:") for r in by_id["chen"].reasons)
    assert by_id["chen"].score > by_id["other"].score