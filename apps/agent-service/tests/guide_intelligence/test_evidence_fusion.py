"""M0 L1: multi-source evidence fusion into TrustedConclusion (pure, offline)."""

from datetime import UTC, datetime, timedelta

from trip_agent.guide_intelligence.evidence_fusion import (
    fuse_facts,
    guide_fact_bonus,
    reliability_rank,
)
from trip_agent.guide_intelligence.trusted_facts import ValidatedFact

NOW = datetime(2026, 9, 1, tzinfo=UTC)


def make_fact(
    *,
    fact_id: str,
    entity: str,
    category: str = "TICKET_PRICE",
    value: dict[str, object],
    reliability: str,
    source_id: str,
    collected_at: datetime,
    source_url: str | None = None,
) -> ValidatedFact:
    return ValidatedFact(
        fact_id=fact_id,
        document_id=f"doc-{fact_id}",
        category=category,
        statement=f"{entity} fact {fact_id}",
        normalized_value=value,
        evidence=f"{entity} evidence {fact_id}",
        evidence_start=0,
        evidence_end=10,
        confidence=0.9,
        checked_at=collected_at,
        expires_at=collected_at + timedelta(days=7),
        effective_date=None,
        source_type="ACQUIRED",
        source_name=source_id,
        source_url=source_url,
        reliability_level=reliability,
        source_reviewed=reliability in {"OFFICIAL_GOV", "OFFICIAL_PORTAL"},
        hard_constraint_eligible=False,
        entity=entity,
        source_id=source_id,
    )


def ticket(amount: float) -> dict[str, object]:
    return {"amount": amount, "currency": "CNY"}


def test_consistent_multi_source_takes_highest_reliability_and_newest() -> None:
    older_gov = make_fact(
        fact_id="gov-old",
        entity="广州塔",
        value=ticket(150),
        reliability="OFFICIAL_GOV",
        source_id="gz-gov",
        collected_at=NOW - timedelta(days=20),
    )
    newer_open = make_fact(
        fact_id="open-new",
        entity="广州塔",
        value=ticket(150),
        reliability="OPEN_DATA",
        source_id="gz-open",
        collected_at=NOW - timedelta(days=2),
    )

    conclusions = fuse_facts((older_gov, newer_open))

    assert len(conclusions) == 1
    conclusion = conclusions[0]
    assert conclusion.status == "VERIFIED"
    assert conclusion.value == ticket(150)
    assert conclusion.entity == "广州塔"
    assert len(conclusion.sources) == 2
    # newest / highest-reliability source survives among sources
    assert {s.source_id for s in conclusion.sources} == {"gz-open", "gz-gov"}


def test_conflict_resolved_by_reliability_over_freshness() -> None:
    gov = make_fact(
        fact_id="gov",
        entity="陈家祠",
        value=ticket(10),
        reliability="OFFICIAL_GOV",
        source_id="gz-gov",
        collected_at=NOW - timedelta(days=30),
    )
    newer_ugc = make_fact(
        fact_id="ugc",
        entity="陈家祠",
        value=ticket(40),
        reliability="UGC",
        source_id="xiaohongshu",
        collected_at=NOW,
    )

    conclusion = fuse_facts((gov, newer_ugc))[0]

    # official reliability wins over the fresher UGC claim
    assert conclusion.status == "VERIFIED"
    assert conclusion.value == ticket(10)


def test_conflict_resolved_by_freshness_within_same_reliability() -> None:
    older = make_fact(
        fact_id="older",
        entity="陈家祠",
        value=ticket(10),
        reliability="OPEN_DATA",
        source_id="gz-open",
        collected_at=NOW - timedelta(days=10),
    )
    newer = make_fact(
        fact_id="newer",
        entity="陈家祠",
        value=ticket(12),
        reliability="OPEN_DATA",
        source_id="gz-culture",
        collected_at=NOW,
    )

    conclusion = fuse_facts((older, newer))[0]

    assert conclusion.value == ticket(12)


def test_undecidable_conflict_is_conflicting_and_not_adopted() -> None:
    a = make_fact(
        fact_id="a",
        entity="沙面",
        value=ticket(0),
        reliability="OPEN_DATA",
        source_id="gz-open",
        collected_at=NOW,
    )
    b = make_fact(
        fact_id="b",
        entity="沙面",
        value=ticket(25),
        reliability="OPEN_DATA",
        source_id="gz-culture",
        collected_at=NOW,
    )

    conclusion = fuse_facts((a, b))[0]

    assert conclusion.status == "CONFLICTING"
    assert conclusion.value is None


def test_single_weak_source_is_unverified_with_low_confidence() -> None:
    weak = make_fact(
        fact_id="ugc",
        entity="农讲所",
        value=ticket(20),
        reliability="UGC",
        source_id="xiaohongshu",
        collected_at=NOW,
    )

    conclusion = fuse_facts((weak,))[0]

    assert conclusion.status == "UNVERIFIED"
    assert conclusion.value == ticket(20)
    assert conclusion.confidence < 0.6  # UGC is low-confidence vs ~0.9 verified


def test_single_strong_source_is_verified() -> None:
    strong = make_fact(
        fact_id="gov",
        entity="农讲所",
        value=ticket(0),
        reliability="OFFICIAL_GOV",
        source_id="gz-gov",
        collected_at=NOW,
    )

    conclusion = fuse_facts((strong,))[0]

    assert conclusion.status == "VERIFIED"


def test_empty_input_yields_no_conclusions() -> None:
    assert fuse_facts(()) == ()


def test_reliability_rank_and_guide_bonus_tier() -> None:
    assert reliability_rank("OFFICIAL_GOV") > reliability_rank("OCR_UNVERIFIED")
    fresh_gov = guide_fact_bonus("OFFICIAL_GOV", NOW, now=NOW)
    stale_ocr = guide_fact_bonus(
        "OCR_UNVERIFIED",
        NOW - timedelta(days=200),
        now=NOW,
    )
    assert fresh_gov - stale_ocr >= 20