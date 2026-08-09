"""B2 RED 4 — hard validator: runs the implemented rules and aggregates a
FeasibilityReport through the B1 builder.

Semantics locked by the catalog: the validator executes exactly the five
implemented rules (in catalog order) while the required set is the full
eleven-rule contract.  Because six required rules remain unimplemented,
``missing_required_rule_ids`` is never empty and the validator can never
report VERIFIED — it may only report UNVERIFIED or NEEDS_REPAIR.  This is
the "no VERIFIED before Hard Validation is complete" safety invariant.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from plan_evaluation_support import make_activity, make_command, make_result

from trip_agent.feasibility.catalog import (
    IMPLEMENTED_RULE_IDS,
    MISSING_RULE_IDS,
    REQUIRED_RULE_IDS,
)
from trip_agent.feasibility.fingerprint import compute_itinerary_fingerprint
from trip_agent.feasibility.models import FeasibilityReport, FeasibilityStatus
from trip_agent.feasibility.validator import validate_itinerary
from trip_agent.worker.contracts import Itinerary, ItineraryDay

REPORT_ID = "4d9b7e0a-3c2f-4a1b-9e8d-7f6e5d4c3b2a"
_TS = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


def _validate(
    *,
    command: object | None = None,
    itinerary: Itinerary | None = None,
) -> FeasibilityReport:
    return validate_itinerary(
        command=command or make_command(),
        itinerary=itinerary or make_result().itinerary,
        report_id=REPORT_ID,
        validated_at=_TS,
    )


# ── rule execution ────────────────────────────────────────────────────────


def test_validator_runs_every_implemented_rule_in_catalog_order() -> None:
    report = _validate()

    assert [result.rule_id for result in report.rule_results] == list(IMPLEMENTED_RULE_IDS)


def test_validator_rule_results_use_the_core_rule_version() -> None:
    report = _validate()

    assert len(report.rule_results) == len(IMPLEMENTED_RULE_IDS)
    assert all(result.rule_version for result in report.rule_results)


# ── aggregation semantics ─────────────────────────────────────────────────


def test_full_pass_is_unverified_because_future_rules_are_missing() -> None:
    report = _validate()

    assert report.status is FeasibilityStatus.UNVERIFIED
    assert report.missing_required_rule_ids == MISSING_RULE_IDS
    assert report.summary.fail_count == 0


def test_fail_rule_yields_needs_repair() -> None:
    command = make_command(budget_amount=Decimal("1000.00"))
    itinerary = make_result(estimated_total_cost=Decimal("1100.00")).itinerary
    report = _validate(command=command, itinerary=itinerary)

    assert report.status is FeasibilityStatus.NEEDS_REPAIR
    assert report.summary.fail_count == 1


def test_validator_never_reports_verified_without_complete_validation() -> None:
    # The invariant: as long as any required rule is unimplemented, the
    # validator must not claim VERIFIED — regardless of the implemented
    # rules all passing.
    command = make_command(budget_amount=None)  # BUDGET_LIMIT -> NOT_APPLICABLE
    report = _validate(command=command)

    assert report.status is FeasibilityStatus.UNVERIFIED
    assert report.status is not FeasibilityStatus.VERIFIED


# ── report fidelity ───────────────────────────────────────────────────────


def test_validator_report_carries_the_contract_fields() -> None:
    itinerary = make_result().itinerary
    report = _validate(itinerary=itinerary)

    assert report.schema_version == 1
    assert report.report_id == UUID(REPORT_ID)
    assert report.validated_at == _TS
    assert report.required_rule_ids == REQUIRED_RULE_IDS
    assert report.itinerary_fingerprint == compute_itinerary_fingerprint(itinerary)


def test_validator_does_not_mutate_the_input_itinerary() -> None:
    itinerary = make_result().itinerary
    before = itinerary.model_dump_json(by_alias=True)

    _validate(itinerary=itinerary)

    assert itinerary.model_dump_json(by_alias=True) == before


def test_validator_handles_oversized_inputs_with_bounded_report() -> None:
    # 65 duplicate POIs (aggregate capped at 64 refs) plus 17 out-of-range
    # days (aggregate capped at 16 dates): the validator must produce a
    # bounded report instead of raising or reporting VERIFIED.
    activities: list = []
    for i in range(65):
        poi = f"P-{i:03d}"
        activities.append(
            make_activity(i, source="AMAP", start_hour=7 + (i % 8)).model_copy(
                update={"provider_poi_id": poi}
            )
        )
        activities.append(
            make_activity(65 + i, source="AMAP", start_hour=7 + (i % 8)).model_copy(
                update={"provider_poi_id": poi}
            )
        )
    days = tuple(
        ItineraryDay(
            date=date(2026, 8, 5) + timedelta(days=i),
            activities=tuple(activities) if i == 0 else (make_activity(0),),
            transit_legs=(),
        )
        for i in range(17)
    )
    itinerary = Itinerary(
        title="Oversized",
        days=days,
        estimated_total_cost=Decimal("100.00"),
    )

    report = _validate(itinerary=itinerary)

    assert report.status is FeasibilityStatus.NEEDS_REPAIR
    assert report.status is not FeasibilityStatus.VERIFIED
    assert report.summary.fail_count >= 2  # DUPLICATE_POI + TRIP_DATE_RANGE
