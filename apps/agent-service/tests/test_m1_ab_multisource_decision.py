"""M1 A/B baseline: prove the M0 multi-source evidence decision beats the old flat guide path.

Runs the exact same multi-source fact fixtures through the OLD path (A: only
flat ``guide_statements``, no ``evidence_facts``) and the NEW path (B: runtime
wired ``evidence_facts`` tiering + ``evidence_strength`` dimension), quantifies
the delta, and asserts all four B>=A requirements plus the DEMO happy path.

The fixture records keep the SAME reliability x recency structure that flows
through ``guide_intelligence.evidence_fusion`` and the ranker tier, so both the
``CandidateRanker.rank`` A/B and the ``PlanEvaluator`` A/B operate on one shared
fixture (statement + entity + normalized_value + reliability + checked_at).
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid5

from plan_evaluation_support import make_command, make_result

from trip_agent.evaluation.evaluator import PlanEvaluator
from trip_agent.evaluation.rules import score_evidence_strength
from trip_agent.evaluation.scoring import weighted_overall_score
from trip_agent.guide_intelligence.evidence_fusion import fuse_facts
from trip_agent.guide_intelligence.trusted_facts import ValidatedFact
from trip_agent.infrastructure.amap.planning_provider import (
    guide_evidence_validated_facts,
)
from trip_agent.planning.candidates import CandidateRanker
from trip_agent.providers.map import Coordinates, Poi

NOW = datetime(2026, 9, 1, tzinfo=UTC)
FIXTURE_NS = UUID("b0ad2a5e-0000-0000-0000-000000000009")


class FrozenClock:
    @classmethod
    def now(cls, tz: object | None = None) -> datetime:
        return NOW


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


def make_fact(
    *,
    key: str,
    entity: str,
    statement: str,
    reliability: str,
    checked_at: datetime,
    value: dict[str, object] | None = None,
    source_id: str = "",
) -> ValidatedFact:
    value = value if value is not None else {"poiName": entity}
    fact_id = uuid5(FIXTURE_NS, f"{entity}-{key}")
    return ValidatedFact(
        fact_id=str(fact_id),
        document_id=f"doc-{fact_id}",
        category="TICKET_PRICE",
        statement=statement,
        normalized_value=value,
        evidence=statement,
        evidence_start=0,
        evidence_end=len(statement),
        confidence=0.9,
        checked_at=checked_at,
        expires_at=checked_at + timedelta(days=7),
        effective_date=None,
        source_type="ACQUIRED",
        source_name=source_id or reliability,
        source_url=None,
        reliability_level=reliability,
        source_reviewed=False,
        hard_constraint_eligible=False,
        entity=entity,
        source_id=source_id or f"src-{reliability}",
    )


# ── Shared multi-source fixture (the SAME set used for rank AND evaluator) ──
# Entity 陈家祠: OFFICIAL recent (positive) <-> 旧 OCR stale (negative, conflict
# value) -> B must pick the official/updated source, A cannot distinguish.
# Entity 沙面艺术馆: single stale OCR fact (weak) -> B tiers it far below
# entity 陈家祠; A flats both at +25.
# Entity 广州塔: two consistent multi-source facts -> fused VERIFIED, high
# evidence_strength; a single UGC fact -> low evidence_strength.

OFFICIAL = make_fact(
    key="official-recent",
    entity="陈家祠",
    statement="陈家祠值得一去，人少方便。",
    reliability="OFFICIAL_GOV",
    checked_at=NOW - timedelta(days=3),
    value={"amount": 30, "currency": "CNY"},
    source_id="gz-gov",
)
STALE_OCR_CONFLICT = make_fact(
    key="ocr-stale",
    entity="陈家祠",
    statement="陈家祠人多不值得排队。",
    reliability="OCR_UNVERIFIED",
    checked_at=NOW - timedelta(days=200),
    value={"amount": 500, "currency": "CNY"},
    source_id="gz-ugc-photo",
)
STALE_OCR_WEAK = make_fact(
    key="ocr-stale-weak",
    entity="沙面艺术馆",
    statement="沙面艺术馆值得一看。",
    reliability="OCR_UNVERIFIED",
    checked_at=NOW - timedelta(days=200),
    value={"amount": 10, "currency": "CNY"},
    source_id="gz-ugc-photo-2",
)
TOWER_A = make_fact(
    key="tower-open",
    entity="广州塔",
    statement="广州塔值得一游，视野好。",
    reliability="OPEN_DATA",
    checked_at=NOW - timedelta(days=1),
    value={"amount": 150, "currency": "CNY"},
    source_id="gz-open-data",
)
TOWER_B = make_fact(
    key="tower-gov",
    entity="广州塔",
    statement="广州塔值得一游，视野好。",
    reliability="OFFICIAL_PORTAL",
    checked_at=NOW,
    value={"amount": 150, "currency": "CNY"},
    source_id="gz-tourism-gov",
)
UGC_WEAK = make_fact(
    key="ugc-single",
    entity="广州塔",
    statement="广州塔值得一游。",
    reliability="UGC",
    checked_at=NOW - timedelta(days=2),
    value={"amount": 150, "currency": "CNY"},
    source_id="xh-user",
)


def _rank(pois, *, evidence_facts=(), guide_statements=(), now=NOW):
    return CandidateRanker().rank(
        pois,
        destination="广州",
        preferences=(),
        traveler_type="SOLO",
        limit=len(pois),
        guide_statements=guide_statements,
        evidence_facts=evidence_facts,
        evidence_now=now,
    )


def _guide_statements(*facts):
    return tuple(f"{f.statement} {f.evidence}" for f in facts)


def _score_by_id(result):
    return {item.poi.provider_id: item for item in result.selected}


# ── 1) B correctly arbitrates a high-reliability/newer source over a weak one ──

def test_b_conflict_resolution_beats_a_flat() -> None:
    facts = (OFFICIAL, STALE_OCR_CONFLICT)
    chen = poi("chen", "陈家祠")
    a = _rank((chen,), guide_statements=_guide_statements(*facts))
    b = _rank((chen,), guide_statements=_guide_statements(*facts), evidence_facts=facts)

    # A: flat +25, reason without source -> cannot tell which source voted.
    a_item = _score_by_id(a)["chen"]
    assert a_item.score == 45
    assert "GUIDE_FACT_MATCH" in a_item.reasons
    assert not any(r.startswith("GUIDE_FACT_MATCH:") for r in a_item.reasons)

    # B: tiered by the OFFICIAL recent source (the newest high-reliability vote),
    # never derailed by the stale OCR.  reason carries the provenance.
    b_item = _score_by_id(b)["chen"]
    assert "GUIDE_FACT_MATCH:OFFICIAL_GOV" in b_item.reasons
    # B's official-tiered boost is not below A's flat boost for the trusted source.
    assert b_item.score >= a_item.score


def test_b_high_reliable_recent_poi_outranks_ocr_stale_poi() -> None:
    facts = (OFFICIAL, STALE_OCR_WEAK)
    chen = poi("chen", "陈家祠")
    shamian = poi("shamian", "沙面艺术馆")
    a = _rank((chen, shamian), guide_statements=_guide_statements(*facts))
    b = _rank((chen, shamian), guide_statements=_guide_statements(*facts), evidence_facts=facts)

    a_rep = _score_by_id(a)
    b_rep = _score_by_id(b)
    # A treats both equal (flat +25) -> cannot tell them apart.
    assert a_rep["chen"].score == a_rep["shamian"].score
    # B strictly separates: official recent vs stale OCR (>= 20 gap), and the
    # reason carries the tiered source for the trusted one.
    assert b_rep["chen"].score - b_rep["shamian"].score >= 20
    assert "GUIDE_FACT_MATCH:OFFICIAL_GOV" in b_rep["chen"].reasons


# ── 2) evidence_strength + overall == weighted invariant (PlanEvaluator) ──

def test_b_evidence_strength_rises_with_sufficiency_overall_invariant() -> None:
    multi = fuse_facts((TOWER_A, TOWER_B))  # two consistent strong sources
    single_weak = fuse_facts((UGC_WEAK,))   # one weak source
    command = make_command(preferences=())

    eval_multi = PlanEvaluator(clock=FrozenClock).evaluate(
        command, make_result(), evidence=multi
    )
    eval_weak = PlanEvaluator(clock=FrozenClock).evaluate(
        command, make_result(), evidence=single_weak
    )
    # Old path: the aggregator had no multi-source evidence -> neutral disclosure.
    eval_a = PlanEvaluator(clock=FrozenClock).evaluate(
        command, make_result(), evidence=()
    )

    assert eval_multi.dimensions.evidence_strength > eval_weak.dimensions.evidence_strength
    assert eval_multi.dimensions.evidence_strength >= 70
    assert eval_weak.dimensions.evidence_strength < 70
    # overall == weighted_overall_score invariant (enforced by the model too).
    assert eval_multi.overall_score == weighted_overall_score(eval_multi.dimensions)
    assert eval_weak.overall_score == weighted_overall_score(eval_weak.dimensions)
    # Multi-source evidence does not drag the aggregate below the old path.
    assert eval_multi.overall_score >= eval_a.overall_score


def test_b_conflicting_evidence_discloses_but_does_not_block() -> None:
    conflicting = (OFFICIAL, STALE_OCR_CONFLICT)  # disagree on amount
    evidence = fuse_facts(conflicting)
    command = make_command(preferences=())
    evaluation = PlanEvaluator(clock=FrozenClock).evaluate(
        command, make_result(), evidence=evidence
    )
    assert evaluation.feasible is True
    assert any("EVIDENCE_STRENGTH" in d.reason_codes for d in evaluation.decisions)
    assert evaluation.overall_score == weighted_overall_score(evaluation.dimensions)


# ── 3) DEMO happy path under B still completes with a non-empty plan ──

def test_b_happy_path_without_evidence_still_completes() -> None:
    # No facts at all -> empty evidence_facts -> ranker falls back to the flat
    # path, evaluator to the neutral baseline.  Nothing crashes.
    chen = poi("chen", "陈家祠")
    happy_rank = CandidateRanker().rank(
        (chen,),
        destination="广州",
        preferences=(),
        traveler_type="SOLO",
        limit=1,
        guide_statements=("陈家祠值得一去。",),
        evidence_facts=(),
        evidence_now=NOW,
    )
    assert happy_rank.selected
    assert happy_rank.selected[0].score == 45

    evaluation = PlanEvaluator(clock=FrozenClock).evaluate(
        make_command(), make_result()
    )
    assert evaluation.feasible is True
    assert evaluation.dimensions.evidence_strength is not None
    # neutral baseline is never a hard failure signal
    assert evaluation.overall_score == weighted_overall_score(evaluation.dimensions)


# ── 4) Runtime wiring really reaches the tiered path ──

def test_runtime_conversion_wires_guide_evidence_into_tiering() -> None:
    """The provider's exact conversion maps GuideFactEvidence source_type to the
    canonical reliability tier, and feeding the converted facts to rank enters
    the evidence path (not the flat guide path)."""

    from trip_agent.worker.contracts import GuideFactEvidence

    def gfe(key: str, statement: str, source_type: str) -> GuideFactEvidence:
        observed = NOW - timedelta(days=2)
        url = "https://www.gz.gov.cn/example"
        return GuideFactEvidence.model_validate(
            {
                "guideImportId": str(uuid5(FIXTURE_NS, f"import-{key}")),
                "factId": str(uuid5(FIXTURE_NS, key)),
                "category": "ATTRACTION",
                "statement": statement,
                "evidence": statement,
                "sourceType": source_type,
                "sourceUrl": url,
                "sourceHost": "www.gz.gov.cn",
                "sourceTitle": "广州攻略",
                "confidence": 0.9,
                "effectiveDate": None,
                "observedAt": observed.astimezone(UTC),
                "expiresAt": observed.astimezone(UTC) + timedelta(days=7),
            }
        )

    facts = (
        gfe("official", "陈家祠值得一去，人少方便。", "OFFICIAL_ATTRACTION"),
        gfe("ocr", "沙面艺术馆值得一看。", "IMAGE_OCR"),
    )
    converted = guide_evidence_validated_facts(facts)
    # source_type -> canonical tier mapping (both official and OCR present).
    assert {f.reliability_level for f in converted} == {"OFFICIAL_PORTAL", "OCR_UNVERIFIED"}
    assert {f.reliability_level for f in converted if f.source_type == "IMAGE_OCR"} == {
        "OCR_UNVERIFIED"
    }

    # feeding the converted facts enters the tiered path (provenance in reason)
    chen = poi("chen", "陈家祠")
    shamian = poi("shamian", "沙面艺术馆")
    result = CandidateRanker().rank(
        (chen, shamian),
        destination="广州",
        preferences=(),
        traveler_type="SOLO",
        limit=2,
        guide_statements=_guide_statements(*converted),
        evidence_facts=converted,
        evidence_now=NOW,
    )
    rep = _score_by_id(result)
    assert any(
        r.startswith("GUIDE_FACT_MATCH:") for r in rep["chen"].reasons
    )
    assert rep["chen"].score != rep["shamian"].score


# ── M1 Task 2: the second trusted source really reaches the same tier ──

def test_second_source_reliability_matches_knowledge_tier_offline() -> None:
    """A CITY_INTELLIGENCE fact (the knowledge / second-trusted-source path) maps
    to the same CURATED tier the source registry declares for
    guangzhou-culture-open-data, then fuses with an official fact into a
    multi-source VERIFIED conclusion feeding evidence_strength."""
    from pathlib import Path

    from trip_agent.acquisition.source_registry import SourceRegistry
    from trip_agent.worker.contracts import GuideFactEvidence

    registry = SourceRegistry.load(Path(__file__).parents[3] / "knowledge" / "sources")
    second = registry.source_by_id("guangzhou-culture-open-data")
    corrupt = second is None or second.reliability_level != "CURATED"
    if corrupt:
        raise AssertionError("guangzhou-culture-open-data must be registered CURATED")

    observed = NOW - timedelta(days=1)
    curated_fact = GuideFactEvidence.model_validate(
        {
            "guideImportId": str(uuid5(FIXTURE_NS, "import-open-data")),
            "factId": str(uuid5(FIXTURE_NS, "open-data-fact")),
            "category": "ATTRACTION",
            "statement": "陈家祠值得一游，免费开放。",
            "evidence": "陈家祠值得一游，免费开放。",
            "sourceType": "CITY_INTELLIGENCE",
            "sourceUrl": "https://data.gz.gov.cn/opendata/resource/gz-attractions",
            "sourceHost": "data.gz.gov.cn",
            "sourceTitle": "广州市文化广电旅游开放数据",
            "confidence": 0.9,
            "effectiveDate": None,
            "observedAt": observed.astimezone(UTC),
            "expiresAt": observed.astimezone(UTC) + timedelta(days=7),
        }
    )
    # The runtime conversion tiers the knowledge path as CURATED == registry.
    (converted,) = guide_evidence_validated_facts((curated_fact,))
    assert converted.reliability_level == "CURATED"
    assert converted.reliability_level == second.reliability_level

    # same POI can be voted by >= 2 independent sources: a CURATED L0 fact (the
    # second trusted source's knowledge fact shape) + an OFFICIAL fact -> fusion
    # marks the entity VERIFIED with multi-source provenance, which drives a high
    # evidence_strength.
    curated_l0 = make_fact(
        key="open-data-l0",
        entity="陈家祠",
        statement="陈家祠值得一游，免费开放。",
        reliability="CURATED",
        checked_at=NOW,
        value={"amount": 0, "currency": "CNY"},
        source_id=second.source_id,
    )
    official = make_fact(
        key="tower-gov-2",
        entity="陈家祠",
        statement="陈家祠值得一游，免费开放。",
        reliability="OFFICIAL_PORTAL",
        checked_at=NOW,
        value={"amount": 0, "currency": "CNY"},
        source_id="gz-gov",
    )
    conclusions = fuse_facts((curated_l0, official))
    assert len(conclusions) == 1
    assert conclusions[0].status == "VERIFIED"
    assert len(conclusions[0].sources) >= 2
    assert {s.source_id for s in conclusions[0].sources} >= {second.source_id}
    assert score_evidence_strength(conclusions) >= 70

    # and the tiered ranking prefers that POI over a weak-only competitor
    chen = poi("chen", "陈家祠")
    other = poi("other", "越秀随便看看")
    b = CandidateRanker().rank(
        (chen, other),
        destination="广州",
        preferences=(),
        traveler_type="SOLO",
        limit=2,
        guide_statements=tuple(f"{official.statement} {official.evidence}"),
        evidence_facts=(curated_l0, official),
        evidence_now=NOW,
    )
    rep = _score_by_id(b)
    assert rep["chen"].score > rep["other"].score
    assert any(r.startswith("GUIDE_FACT_MATCH:") for r in rep["chen"].reasons)