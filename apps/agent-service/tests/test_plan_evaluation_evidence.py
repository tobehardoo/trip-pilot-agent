"""M0 L4/L5: evidence-strength dimension and EVIDENCE_STRENGTH disclosure."""

from datetime import UTC, datetime, timedelta

from plan_evaluation_support import make_command, make_result

from trip_agent.evaluation.evaluator import PlanEvaluator
from trip_agent.evaluation.rules import score_evidence_strength
from trip_agent.evaluation.scoring import weighted_overall_score
from trip_agent.guide_intelligence.evidence_fusion import TrustedConclusion, fuse_facts
from trip_agent.guide_intelligence.trusted_facts import ValidatedFact

NOW = datetime(2026, 9, 1, tzinfo=UTC)


class FrozenClock:
    @classmethod
    def now(cls, tz: object | None = None) -> datetime:
        return NOW


def make_fact(
    *,
    fact_id: str,
    value: dict[str, object],
    reliability: str,
    source_id: str,
    collected_at: datetime,
) -> ValidatedFact:
    return ValidatedFact(
        fact_id=fact_id,
        document_id=f"doc-{fact_id}",
        category="TICKET_PRICE",
        statement=f"{source_id} ticket",
        normalized_value=value,
        evidence=f"{source_id} evidence",
        evidence_start=0,
        evidence_end=12,
        confidence=0.9,
        checked_at=collected_at,
        expires_at=collected_at + timedelta(days=7),
        effective_date=None,
        source_type="ACQUIRED",
        source_name=source_id,
        source_url=None,
        reliability_level=reliability,
        source_reviewed=False,
        hard_constraint_eligible=False,
        entity="广州塔",
        source_id=source_id,
    )


def _ticket(amount: float) -> dict[str, object]:
    return {"amount": amount, "currency": "CNY"}


def test_evidence_strength_rises_with_sufficiency() -> None:
    strong = (
        make_fact(
            fact_id="gov", value=_ticket(150), reliability="OFFICIAL_GOV",
            source_id="gz-gov", collected_at=NOW,
        ),
        make_fact(
            fact_id="open", value=_ticket(150), reliability="OPEN_DATA",
            source_id="gz-open", collected_at=NOW,
        ),
    )
    weak = (
        make_fact(
            fact_id="ugc", value=_ticket(150), reliability="UGC",
            source_id="xh", collected_at=NOW,
        ),
    )
    strong_conclusions = fuse_facts(strong)
    weak_conclusions = fuse_facts(weak)

    high = score_evidence_strength(strong_conclusions)
    low = score_evidence_strength(weak_conclusions)

    assert high > low


def test_evaluator_emits_evidence_dimension_and_disclosure_decision() -> None:
    conclusions = (
        make_fact(
            fact_id="gov", value=_ticket(150), reliability="OFFICIAL_GOV",
            source_id="gz-gov", collected_at=NOW,
        ),
        make_fact(
            fact_id="open", value=_ticket(150), reliability="OPEN_DATA",
            source_id="gz-open", collected_at=NOW,
        ),
    )
    evidence = fuse_facts(conclusions)

    evaluation = PlanEvaluator(clock=FrozenClock).evaluate(
        make_command(preferences=()), make_result(), evidence=evidence
    )

    assert evaluation.evaluator_version == "rule-v6"
    assert evaluation.dimensions.evidence_strength is not None
    assert evaluation.dimensions.evidence_strength >= 70
    # overall == weighted sum invariant holds for the emitted plan
    assert evaluation.overall_score == weighted_overall_score(evaluation.dimensions)
    assert evaluation.feasible is True
    disclosure = next(
        item
        for item in evaluation.decisions
        if "EVIDENCE_STRENGTH" in item.reason_codes
    )
    assert disclosure.subject_type == "PLAN"


def test_neutral_evidence_dimension_keeps_happy_path_completed() -> None:
    evaluation = PlanEvaluator(clock=FrozenClock).evaluate(
        make_command(), make_result()
    )

    assert evaluation.feasible is True
    assert evaluation.dimensions.evidence_strength is not None


def test_conflicting_evidence_pulls_dimension_down() -> None:
    conflicting = (
        TrustedConclusion(
            entity="沙面",
            property="TICKET_PRICE",
            value=None,
            status="CONFLICTING",
            confidence=0.15,
            sources=(),
        ),
    )
    low = score_evidence_strength(conflicting)
    medium = score_evidence_strength(
        (
            TrustedConclusion(
                entity="广州塔",
                property="TICKET_PRICE",
                value=_ticket(150),
                status="UNVERIFIED",
                confidence=0.4,
                sources=(),
            ),
        )
    )
    assert low < medium