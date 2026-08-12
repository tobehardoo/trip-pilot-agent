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
    REQUIRED_RULE_IDS,
)
from trip_agent.feasibility.fingerprint import compute_itinerary_fingerprint
from trip_agent.feasibility.models import FeasibilityReport, FeasibilityStatus
from trip_agent.feasibility.validator import validate_itinerary
from trip_agent.planning.trip_skeleton import TripSkeleton
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


def test_full_pass_is_unverified_without_validation_inputs() -> None:
    # All eleven rules now exist; the fixture itinerary carries no opening /
    # duration / meal inputs, so the new rules are UNKNOWN -> UNVERIFIED.
    report = _validate()

    assert report.status is FeasibilityStatus.UNVERIFIED
    assert report.missing_required_rule_ids == ()
    assert report.summary.fail_count == 0
    assert report.summary.unknown_count >= 1


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


# ── B4B Phase 1: optional trip skeleton input ──────────────────────────────


def _skeleton() -> TripSkeleton:
    from trip_agent.planning.daily_schedule import DayPlan
    from trip_agent.planning.trip_skeleton import (
        UnresolvedAccommodation,
        build_trip_skeleton,
    )

    def _day(day: date) -> DayPlan:
        return DayPlan(
            date=day,
            day_type="FULL_DAY",
            window_start_minute=540,
            window_end_minute=1080,
            items=(),
            meal_demands=(),
            origin=None,
            accommodation_unknown=False,
            warnings=(),
        )

    return build_trip_skeleton(
        (_day(date(2026, 8, 1)), _day(date(2026, 8, 2))),
        (UnresolvedAccommodation(),),
    )


def test_validation_context_carries_trip_skeleton() -> None:
    from trip_agent.feasibility.context import ValidationContext, build_budget_context

    command = make_command()
    itinerary = make_result().itinerary
    skeleton = _skeleton()
    ctx = ValidationContext(
        command=command,
        itinerary=itinerary,
        budget=build_budget_context(command, itinerary),
        trip_skeleton=skeleton,
    )

    assert ctx.trip_skeleton is skeleton


def test_validation_context_defaults_trip_skeleton_to_none() -> None:
    from trip_agent.feasibility.context import ValidationContext, build_budget_context

    command = make_command()
    itinerary = make_result().itinerary
    ctx = ValidationContext(
        command=command,
        itinerary=itinerary,
        budget=build_budget_context(command, itinerary),
    )

    assert ctx.trip_skeleton is None


def test_validate_itinerary_accepts_trip_skeleton_keyword() -> None:
    report = validate_itinerary(
        command=make_command(),
        itinerary=make_result().itinerary,
        report_id=REPORT_ID,
        validated_at=_TS,
        trip_skeleton=_skeleton(),
    )

    assert report.status is FeasibilityStatus.UNVERIFIED


def test_validate_itinerary_without_trip_skeleton_stays_compatible() -> None:
    report = validate_itinerary(
        command=make_command(),
        itinerary=make_result().itinerary,
        report_id=REPORT_ID,
        validated_at=_TS,
    )

    assert report.status is FeasibilityStatus.UNVERIFIED


def test_validate_itinerary_does_not_mutate_skeleton_or_itinerary() -> None:
    skeleton = _skeleton()
    itinerary = make_result().itinerary
    before_days = tuple(skeleton.days)
    before_activities = tuple(itinerary.days[0].activities)

    validate_itinerary(
        command=make_command(),
        itinerary=itinerary,
        report_id=REPORT_ID,
        validated_at=_TS,
        trip_skeleton=skeleton,
    )

    assert skeleton.days == before_days
    assert itinerary.days[0].activities == before_activities


# ── B4B Phase 4: continuity rules in dispatch ──────────────────────────────


def test_validator_version_is_v5() -> None:
    report = _validate()

    assert report.validator_version == "hard-validator-v5"


def test_validator_rule_order_matches_implemented_set() -> None:
    report = _validate()

    assert [result.rule_id for result in report.rule_results] == list(IMPLEMENTED_RULE_IDS)
    assert len(report.rule_results) == 11


def test_route_unknown_keeps_report_unverified() -> None:
    # Demo itinerary: activities without coordinates -> route rule UNKNOWN.
    report = _validate()

    route = next(
        result for result in report.rule_results if result.rule_id == "ROUTE_ENDPOINT_CONTINUITY"
    )
    assert route.outcome.value == "UNKNOWN"
    assert report.status is FeasibilityStatus.UNVERIFIED


def test_cross_unknown_keeps_report_unverified() -> None:
    from datetime import date as date_cls

    from trip_agent.planning.daily_schedule import DayPlan
    from trip_agent.planning.trip_skeleton import (
        UnresolvedAccommodation,
        build_trip_skeleton,
    )

    day_one = ItineraryDay(
        date=date_cls(2026, 8, 1),
        activities=(make_activity(0),),
        transit_legs=(),
    )
    day_two = ItineraryDay(
        date=date_cls(2026, 8, 2),
        activities=(make_activity(1),),
        transit_legs=(),
    )
    itinerary = Itinerary(
        title="Two days",
        days=(day_one, day_two),
        estimated_total_cost=Decimal("100.00"),
    )

    def _day(day: date_cls) -> DayPlan:
        return DayPlan(
            date=day,
            day_type="FULL_DAY",
            window_start_minute=540,
            window_end_minute=1080,
            items=(),
            meal_demands=(),
            origin=None,
            accommodation_unknown=False,
            warnings=(),
        )

    skeleton = build_trip_skeleton(
        (_day(date_cls(2026, 8, 1)), _day(date_cls(2026, 8, 2))),
        (UnresolvedAccommodation(),),
    )
    report = _validate(itinerary=itinerary)
    assert report.status is FeasibilityStatus.UNVERIFIED

    report_with_skeleton = validate_itinerary(
        command=make_command(),
        itinerary=itinerary,
        report_id=REPORT_ID,
        validated_at=_TS,
        trip_skeleton=skeleton,
    )
    cross = next(
        result
        for result in report_with_skeleton.rule_results
        if result.rule_id == "CROSS_DAY_CONTINUITY"
    )
    assert cross.outcome.value == "UNKNOWN"
    assert report_with_skeleton.status is FeasibilityStatus.UNVERIFIED


def test_continuity_fail_yields_needs_repair() -> None:
    # AMap itinerary: activities have coordinates but no transit legs ->
    # ROUTE_ENDPOINT_CONTINUITY FAIL -> NEEDS_REPAIR.
    activities = (
        make_activity(0, source="AMAP", start_hour=9),
        make_activity(1, source="AMAP", start_hour=11),
    )
    itinerary = Itinerary(
        title="No legs",
        days=(
            ItineraryDay(
                date=date(2026, 8, 1),
                activities=activities,
                transit_legs=(),
            ),
        ),
        estimated_total_cost=Decimal("100.00"),
    )

    report = _validate(itinerary=itinerary)

    route = next(
        result for result in report.rule_results if result.rule_id == "ROUTE_ENDPOINT_CONTINUITY"
    )
    assert route.outcome.value == "FAIL"
    assert report.status is FeasibilityStatus.NEEDS_REPAIR


def test_fail_rule_precedes_unknown_in_aggregation() -> None:
    # One FAIL (budget) plus UNKNOWN route/cross -> still NEEDS_REPAIR.
    command = make_command(budget_amount=Decimal("1000.00"))
    itinerary = make_result(estimated_total_cost=Decimal("1100.00")).itinerary

    report = _validate(command=command, itinerary=itinerary)

    assert report.status is FeasibilityStatus.NEEDS_REPAIR
    assert report.summary.fail_count >= 1
    assert report.summary.unknown_count >= 1
