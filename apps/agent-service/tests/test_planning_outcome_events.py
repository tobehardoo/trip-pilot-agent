"""B6 — authoritative outcome events: v10/v11 completion and review-required v2.

Locks the event-model semantics before the worker wiring: v10/v11 payloads
require a PlanEvaluation and bind the feasibility report to the itinerary
fingerprint; completion accepts VERIFIED or savable UNVERIFIED reports but
never a blocker; review v2 accepts only UNVERIFIED / NEEDS_REPAIR reports
and never carries a PlanEvaluation.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from plan_evaluation_support import make_command, make_result
from pydantic import ValidationError

from trip_agent.evaluation.models import PlanEvaluation
from trip_agent.feasibility.models import FeasibilityStatus
from trip_agent.feasibility.validator import validate_itinerary
from trip_agent.worker.contracts import (
    KnowledgeCitationSnapshot,
    KnowledgeEvidence,
    KnowledgeFreshness,
    PlanningCompletedEventV11,
    PlanningCompletedPayloadV10,
    PlanningReviewRequiredEventV2,
    PlanningReviewRequiredPayload,
)

REPORT_ID = "3d76fb9e-362e-4b28-8a9e-18e8ac7050ad"
_TS = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
_COMMAND = make_command()


def _knowledge() -> KnowledgeEvidence:
    return KnowledgeEvidence(
        status="REAL",
        query="广州 历史",
        citations=(
            KnowledgeCitationSnapshot(
                document_id="guangzhou-history-001",
                document_version=2,
                chunk_id="guangzhou-history-001-0",
                chunk_index=0,
                title="广州历史",
                source_url="https://example.com/guangzhou",
                source_name="示例",
                collected_at=_TS - timedelta(days=1),
                reliability_level="HIGH",
                similarity=0.9,
            ),
        ),
        freshness=KnowledgeFreshness(
            status="FRESH",
            checked_at=_TS - timedelta(days=1),
        ),
    )


def _identity() -> dict[str, object]:
    return {
        "event_id": UUID(int=1),
        "trace_id": UUID(int=2),
        "task_id": UUID(int=3),
        "trip_id": UUID(int=4),
        "run_id": UUID(int=5),
        "occurred_at": _TS,
    }


def _report() -> object:
    itinerary = make_result().itinerary
    report = validate_itinerary(
        command=_COMMAND,
        itinerary=itinerary,
        report_id=REPORT_ID,
        validated_at=_TS,
    )
    return report


def _evaluation() -> PlanEvaluation:
    from trip_agent.evaluation import get_plan_evaluator

    return get_plan_evaluator().evaluate(make_command(), make_result())


def test_v10_payload_rejects_missing_report() -> None:
    with pytest.raises(ValidationError):
        PlanningCompletedPayloadV10(
            provider="DEMO",
            itinerary=make_result().itinerary,
            knowledge=_knowledge(),
            fact_impacts=(),
            provider_provenance=None,
            evaluation=None,
            feasibility_report=None,
            has_blocker=False,
        )


def test_review_v2_accepts_unverified_report() -> None:
    event = PlanningReviewRequiredEventV2(
        event_type="PLANNING_REVIEW_REQUIRED",
        schema_version=2,
        **_identity(),
        payload=PlanningReviewRequiredPayload(
            status="WAITING_USER",
            provider="DEMO",
            itinerary=make_result().itinerary,
            knowledge=_knowledge(),
            fact_impacts=(),
            provider_provenance=None,
            feasibility_report=_report(),
        ),
    )

    assert event.payload.status == "WAITING_USER"
    assert event.payload.feasibility_report.status is FeasibilityStatus.UNVERIFIED


def test_review_rejects_verified_report() -> None:
    from trip_agent.feasibility.catalog import IMPLEMENTED_RULE_IDS
    from trip_agent.feasibility.fingerprint import compute_itinerary_fingerprint
    from trip_agent.feasibility.models import (
        RuleOutcome,
        RuleResult,
        build_feasibility_report,
    )

    itinerary = make_result().itinerary
    results = tuple(
        RuleResult(
            rule_id=rule_id,
            rule_version="hard-rule-v1",
            outcome=RuleOutcome.NOT_APPLICABLE,
            reason_code="N/A",
            message="na",
        )
        for rule_id in IMPLEMENTED_RULE_IDS
    )
    verified = build_feasibility_report(
        report_id=REPORT_ID,
        validator_version="hard-validator-v3",
        itinerary_fingerprint=compute_itinerary_fingerprint(itinerary),
        validated_at=_TS,
        required_rule_ids=IMPLEMENTED_RULE_IDS,
        rule_results=results,
    )
    with pytest.raises(ValidationError):
        PlanningReviewRequiredPayload(
            status="WAITING_USER",
            provider="DEMO",
            itinerary=itinerary,
            knowledge=_knowledge(),
            fact_impacts=(),
            provider_provenance=None,
            feasibility_report=verified,
        )


def test_review_has_no_evaluation_field() -> None:
    payload = PlanningReviewRequiredPayload(
        status="WAITING_USER",
        provider="DEMO",
        itinerary=make_result().itinerary,
        knowledge=_knowledge(),
        fact_impacts=(),
        provider_provenance=None,
        feasibility_report=_report(),
    )

    assert not hasattr(payload, "evaluation")
    assert "evaluation" not in type(payload).model_fields


def test_outcome_events_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        PlanningReviewRequiredPayload(
            status="WAITING_USER",
            provider="DEMO",
            itinerary=make_result().itinerary,
            knowledge=_knowledge(),
            fact_impacts=(),
            provider_provenance=None,
            feasibility_report=_report(),
            bogus="x",
        )


# ── B6.1: evaluation required + itinerary fingerprint binding ──────────────


def test_v10_payload_requires_evaluation() -> None:
    report = _report()
    with pytest.raises(ValidationError):
        PlanningCompletedPayloadV10(
            provider="DEMO",
            itinerary=make_result().itinerary,
            knowledge=_knowledge(),
            fact_impacts=(),
            provider_provenance=None,
            feasibility_report=report,
            has_blocker=False,
        )


def test_v10_payload_rejects_none_evaluation() -> None:
    with pytest.raises(ValidationError):
        PlanningCompletedPayloadV10(
            provider="DEMO",
            itinerary=make_result().itinerary,
            knowledge=_knowledge(),
            fact_impacts=(),
            provider_provenance=None,
            evaluation=None,
            feasibility_report=_report(),
            has_blocker=False,
        )


def test_v10_payload_rejects_non_evaluation_object() -> None:
    with pytest.raises(ValidationError):
        PlanningCompletedPayloadV10(
            provider="DEMO",
            itinerary=make_result().itinerary,
            knowledge=_knowledge(),
            fact_impacts=(),
            provider_provenance=None,
            evaluation="not an evaluation",
            feasibility_report=_report(),
            has_blocker=False,
        )


def test_v10_payload_rejects_fingerprint_mismatch() -> None:
    from trip_agent.feasibility.catalog import IMPLEMENTED_RULE_IDS
    from trip_agent.feasibility.fingerprint import compute_itinerary_fingerprint
    from trip_agent.feasibility.models import (
        RuleOutcome,
        RuleResult,
        build_feasibility_report,
    )

    other_itinerary = make_result().itinerary
    results = tuple(
        RuleResult(
            rule_id=rid,
            rule_version="hard-rule-v1",
            outcome=RuleOutcome.NOT_APPLICABLE,
            reason_code="N/A",
            message="na",
        )
        for rid in IMPLEMENTED_RULE_IDS
    )
    report = build_feasibility_report(
        report_id=REPORT_ID,
        validator_version="hard-validator-v3",
        itinerary_fingerprint=compute_itinerary_fingerprint(other_itinerary),
        validated_at=_TS,
        required_rule_ids=IMPLEMENTED_RULE_IDS,
        rule_results=results,
    )
    # payload carries a different itinerary than the report fingerprint.
    from datetime import timedelta

    from trip_agent.worker.contracts import Itinerary, ItineraryActivity, ItineraryDay

    other = Itinerary(
        title="other",
        days=(
            ItineraryDay(
                date=__import__("datetime").date(2026, 8, 2),
                activities=(
                    ItineraryActivity(
                        activity_id=UUID(int=99),
                        title="X",
                        start_time=_TS,
                        end_time=_TS + timedelta(minutes=30),
                        estimated_cost=Decimal("1.00"),
                        source="DEMO",
                        kind="ATTRACTION",
                    ),
                ),
                transit_legs=(),
            ),
        ),
        estimated_total_cost=Decimal("1.00"),
    )
    with pytest.raises(ValidationError):
        PlanningCompletedPayloadV10(
            provider="DEMO",
            itinerary=other,
            knowledge=_knowledge(),
            fact_impacts=(),
            provider_provenance=None,
            evaluation=_evaluation(),
            feasibility_report=report,
            has_blocker=False,
        )


def test_review_payload_rejects_fingerprint_mismatch() -> None:
    from trip_agent.feasibility.catalog import IMPLEMENTED_RULE_IDS
    from trip_agent.feasibility.fingerprint import compute_itinerary_fingerprint
    from trip_agent.feasibility.models import (
        RuleOutcome,
        RuleResult,
        build_feasibility_report,
    )
    from trip_agent.worker.contracts import Itinerary, ItineraryActivity, ItineraryDay

    other_itinerary = make_result().itinerary
    results = tuple(
        RuleResult(
            rule_id=rid,
            rule_version="hard-rule-v1",
            outcome=RuleOutcome.UNKNOWN,
            reason_code="OPENING_HOURS_UNVERIFIED",
            message="no evidence",
        )
        for rid in IMPLEMENTED_RULE_IDS
    )
    report = build_feasibility_report(
        report_id=REPORT_ID,
        validator_version="hard-validator-v3",
        itinerary_fingerprint=compute_itinerary_fingerprint(other_itinerary),
        validated_at=_TS,
        required_rule_ids=IMPLEMENTED_RULE_IDS,
        rule_results=results,
    )
    other = Itinerary(
        title="other review",
        days=(
            ItineraryDay(
                date=__import__("datetime").date(2026, 8, 2),
                activities=(
                    ItineraryActivity(
                        activity_id=UUID(int=98),
                        title="Y",
                        start_time=_TS,
                        end_time=_TS + timedelta(minutes=30),
                        estimated_cost=Decimal("1.00"),
                        source="DEMO",
                        kind="ATTRACTION",
                    ),
                ),
                transit_legs=(),
            ),
        ),
        estimated_total_cost=Decimal("1.00"),
    )
    with pytest.raises(ValidationError):
        PlanningReviewRequiredPayload(
            status="WAITING_USER",
            provider="DEMO",
            itinerary=other,
            knowledge=_knowledge(),
            fact_impacts=(),
            provider_provenance=None,
            feasibility_report=report,
        )


# ── B16: completion (v10 payload / v11 event) — Information Missing != Planning Failed ──


def _verified_report():
    from trip_agent.feasibility.catalog import IMPLEMENTED_RULE_IDS
    from trip_agent.feasibility.fingerprint import compute_itinerary_fingerprint
    from trip_agent.feasibility.models import (
        RuleOutcome,
        RuleResult,
        build_feasibility_report,
    )

    itinerary = make_result().itinerary
    results = tuple(
        RuleResult(
            rule_id=rule_id,
            rule_version="hard-rule-v1",
            outcome=RuleOutcome.NOT_APPLICABLE,
            reason_code="N/A",
            message="na",
        )
        for rule_id in IMPLEMENTED_RULE_IDS
    )
    return build_feasibility_report(
        report_id=REPORT_ID,
        validator_version="hard-validator-v5",
        itinerary_fingerprint=compute_itinerary_fingerprint(itinerary),
        validated_at=_TS,
        required_rule_ids=IMPLEMENTED_RULE_IDS,
        rule_results=results,
    )


def test_v11_accepts_verified_report() -> None:
    report = _verified_report()
    assert report.status is FeasibilityStatus.VERIFIED
    assert report.has_blocker is False

    event = PlanningCompletedEventV11(
        event_type="PLANNING_COMPLETED",
        schema_version=11,
        **_identity(),
        payload=PlanningCompletedPayloadV10(
            provider="DEMO",
            itinerary=make_result().itinerary,
            knowledge=_knowledge(),
            fact_impacts=(),
            provider_provenance=None,
            evaluation=_evaluation(),
            feasibility_report=report,
            has_blocker=False,
        ),
    )
    assert event.schema_version == 11
    assert event.payload.feasibility_report.status is FeasibilityStatus.VERIFIED
    assert event.payload.has_blocker is False


def test_v11_accepts_unverified_no_blocker_report() -> None:
    """3 opening-hours unknowns + 4 duration unknowns -> savable v11."""
    report = _report()  # fixture demo itinerary has no evidence -> UNVERIFIED
    assert report.status is FeasibilityStatus.UNVERIFIED
    assert report.has_blocker is False
    assert report.can_save is True

    event = PlanningCompletedEventV11(
        event_type="PLANNING_COMPLETED",
        schema_version=11,
        **_identity(),
        payload=PlanningCompletedPayloadV10(
            provider="DEMO",
            itinerary=make_result().itinerary,
            knowledge=_knowledge(),
            fact_impacts=(),
            provider_provenance=None,
            evaluation=_evaluation(),
            feasibility_report=report,
            has_blocker=False,
        ),
    )
    assert event.payload.feasibility_report.status is FeasibilityStatus.UNVERIFIED
    assert event.payload.has_blocker is False


def test_v11_rejects_blocker_report() -> None:
    """A FAIL (venue closed) must never be emitted as a completion event."""
    from trip_agent.feasibility.catalog import IMPLEMENTED_RULE_IDS
    from trip_agent.feasibility.fingerprint import compute_itinerary_fingerprint
    from trip_agent.feasibility.models import (
        EvidenceReference,
        EvidenceState,
        RuleOutcome,
        RuleResult,
        build_feasibility_report,
    )

    itinerary = make_result().itinerary
    results = tuple(
        RuleResult(
            rule_id=rule_id,
            rule_version="hard-rule-v1",
            outcome=RuleOutcome.NOT_APPLICABLE,
            reason_code="N/A",
            message="na",
        )
        for rule_id in IMPLEMENTED_RULE_IDS
        if rule_id != "OPENING_HOURS"
    ) + (
        RuleResult(
            rule_id="OPENING_HOURS",
            rule_version="hard-rule-v1",
            outcome=RuleOutcome.FAIL,
            reason_code="VENUE_CLOSED",
            message="closed",
            evidence_refs=(
                EvidenceReference(
                    evidence_id="ev:opening",
                    evidence_type="OPENING_HOURS",
                    state=EvidenceState.VERIFIED,
                    hard_constraint_eligible=True,
                ),
            ),
        ),
    )
    report = build_feasibility_report(
        report_id=REPORT_ID,
        validator_version="hard-validator-v5",
        itinerary_fingerprint=compute_itinerary_fingerprint(itinerary),
        validated_at=_TS,
        required_rule_ids=IMPLEMENTED_RULE_IDS,
        rule_results=results,
    )
    assert report.has_blocker is True

    with pytest.raises(ValidationError):
        PlanningCompletedEventV11(
            event_type="PLANNING_COMPLETED",
            schema_version=11,
            **_identity(),
            payload=PlanningCompletedPayloadV10(
                provider="DEMO",
                itinerary=itinerary,
                knowledge=_knowledge(),
                fact_impacts=(),
                provider_provenance=None,
                evaluation=_evaluation(),
                feasibility_report=report,
                has_blocker=True,
            ),
        )


def test_v10_payload_rejects_has_blocker_mismatch() -> None:
    report = _verified_report()
    with pytest.raises(ValidationError):
        PlanningCompletedPayloadV10(
            provider="DEMO",
            itinerary=make_result().itinerary,
            knowledge=_knowledge(),
            fact_impacts=(),
            provider_provenance=None,
            evaluation=_evaluation(),
            feasibility_report=report,
            has_blocker=True,  # mismatch: report says no blocker
        )
