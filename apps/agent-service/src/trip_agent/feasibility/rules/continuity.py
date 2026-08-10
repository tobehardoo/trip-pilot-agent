"""B4B — continuity hard rules.

``assess_route_endpoint_continuity`` checks, within each ItineraryDay, that
every adjacent activity pair (in tuple order) has an explicit transit leg
when both endpoints carry coordinates.  Missing endpoint coordinates are an
evidence gap (UNKNOWN), never a defect — a Demo activity is never judged
PASS merely because an estimated leg exists.

``assess_cross_day_continuity`` checks the overnight bridge between
consecutive days against the transient TripSkeleton.  Only a matching
CONFIRMED accommodation can PASS; AREA_ESTIMATED / UNRESOLVED
accommodation, a missing skeleton or a date mismatch are all evidence gaps
(UNKNOWN).  A CONFIRMED endpoint mismatch is the only FAIL source.

Both rules are pure, deterministic and never mutate their inputs.  They do
not import providers, evaluation or worker processor code, and they never
treat the skeleton as external VERIFIED evidence.
"""

from __future__ import annotations

from datetime import date

from trip_agent.feasibility.context import ValidationContext
from trip_agent.feasibility.models import RuleOutcome, RuleResult
from trip_agent.feasibility.rules.core import (
    MAX_AFFECTED_DATES,
    MAX_AFFECTED_ENTITY_REFS,
    RULE_VERSION,
    RuleAssessment,
    RuleFinding,
)
from trip_agent.worker.contracts import ItineraryActivity

ROUTE_RULE_ID = "ROUTE_ENDPOINT_CONTINUITY"
CROSS_RULE_ID = "CROSS_DAY_CONTINUITY"


def _activity_ref(activity: ItineraryActivity) -> str | None:
    if activity.activity_id is not None:
        return str(activity.activity_id)
    if activity.provider_poi_id is not None:
        return activity.provider_poi_id
    return None


def _bounded_dates(dates: set[date]) -> tuple[date, ...]:
    return tuple(sorted(dates))[:MAX_AFFECTED_DATES]


def _bounded_refs(refs: set[str]) -> tuple[str, ...]:
    return tuple(sorted(refs))[:MAX_AFFECTED_ENTITY_REFS]


def _result(
    rule_id: str,
    outcome: RuleOutcome,
    reason_code: str,
    message: str,
    *,
    affected_dates: tuple[date, ...] = (),
    affected_entity_refs: tuple[str, ...] = (),
) -> RuleResult:
    return RuleResult(
        rule_id=rule_id,
        rule_version=RULE_VERSION,
        outcome=outcome,
        reason_code=reason_code,
        message=message,
        affected_dates=affected_dates,
        affected_entity_refs=affected_entity_refs,
    )


# ── ROUTE_ENDPOINT_CONTINUITY ──────────────────────────────────────────────


def assess_route_endpoint_continuity(ctx: ValidationContext) -> RuleAssessment:
    """Every adjacent activity pair inside a day needs an explicit leg.

    Both endpoints must carry coordinates for the pair to be verifiable;
    otherwise the pair is UNKNOWN even if a leg exists.  Any missing-leg
    pair makes the whole rule FAIL; otherwise any UNKNOWN pair makes it
    UNKNOWN; all-verifiable-with-leg makes it PASS; no pairs makes it N/A.
    """
    findings: list[RuleFinding] = []
    pair_count = 0
    fail_count = 0
    unknown_count = 0
    affected_dates: set[date] = set()
    affected_refs: set[str] = set()

    for day in ctx.itinerary.days:
        activities = day.activities
        if len(activities) < 2:
            continue
        leg_pairs = {(leg.from_activity_index, leg.to_activity_index) for leg in day.transit_legs}
        for index in range(len(activities) - 1):
            pair_count += 1
            first = activities[index]
            second = activities[index + 1]
            has_leg = (index, index + 1) in leg_pairs
            if first.coordinates is None or second.coordinates is None:
                unknown_count += 1
                affected_dates.add(day.date)
                pair_refs = tuple(
                    ref
                    for activity in (first, second)
                    for ref in (_activity_ref(activity),)
                    if ref is not None
                )
                affected_refs.update(pair_refs)
                findings.append(
                    RuleFinding(
                        reason_code="ROUTE_ENDPOINT_COORDINATES_MISSING",
                        message=(
                            f"day {day.date} pair ({index}, {index + 1}) has "
                            "an endpoint without coordinates"
                        ),
                        affected_date=day.date,
                        affected_entity_refs=pair_refs,
                    )
                )
            elif not has_leg:
                fail_count += 1
                affected_dates.add(day.date)
                pair_refs = tuple(
                    ref
                    for activity in (first, second)
                    for ref in (_activity_ref(activity),)
                    if ref is not None
                )
                affected_refs.update(pair_refs)
                findings.append(
                    RuleFinding(
                        reason_code="ROUTE_LEG_MISSING",
                        message=(
                            f"day {day.date} pair ({index}, {index + 1}) has "
                            "coordinates but no transit leg"
                        ),
                        affected_date=day.date,
                        affected_entity_refs=pair_refs,
                    )
                )

    if pair_count == 0:
        return RuleAssessment(
            result=_result(
                ROUTE_RULE_ID,
                RuleOutcome.NOT_APPLICABLE,
                "NO_ADJACENT_ACTIVITY_PAIRS",
                "no adjacent activity pairs to verify",
            )
        )
    if fail_count > 0:
        outcome = RuleOutcome.FAIL
        reason_code = "ROUTE_LEG_MISSING"
        message = f"{fail_count} adjacent pair(s) missing a transit leg"
    elif unknown_count > 0:
        outcome = RuleOutcome.UNKNOWN
        reason_code = "ROUTE_ENDPOINTS_UNVERIFIABLE"
        message = f"{unknown_count} adjacent pair(s) have unverifiable endpoints"
    else:
        outcome = RuleOutcome.PASS
        reason_code = "ROUTE_ENDPOINTS_CONTINUOUS"
        message = "every adjacent activity pair has an explicit transit leg"
    return RuleAssessment(
        result=_result(
            ROUTE_RULE_ID,
            outcome,
            reason_code,
            message,
            affected_dates=_bounded_dates(affected_dates),
            affected_entity_refs=_bounded_refs(affected_refs),
        ),
        findings=tuple(findings),
    )


# ── CROSS_DAY_CONTINUITY ───────────────────────────────────────────────────


def _quantised_decimal(value: object) -> object:
    """Quantise a Decimal to the project's COORDINATE_SCALE.

    Both sides of the comparison go through the same scale so a
    high-precision tail on either side never causes a false conflict.
    """
    from decimal import Decimal

    from trip_agent.domain.shared import COORDINATE_SCALE

    if not isinstance(value, Decimal):
        return value
    return value.quantize(COORDINATE_SCALE)


def _confirmed_matches_activity(
    confirmed: object,
    activity: ItineraryActivity,
) -> bool:
    """Return whether an accommodation activity node matches the CONFIRMED
    skeleton accommodation (kind, POI id and quantised coordinates)."""
    from trip_agent.planning.trip_skeleton import ConfirmedAccommodation

    if not isinstance(confirmed, ConfirmedAccommodation):
        return False
    if activity.kind != "ACCOMMODATION":
        return False
    if activity.provider_poi_id != confirmed.provider_poi_id:
        return False
    if activity.coordinates is None:
        return False
    from trip_agent.domain.shared import coordinate_decimal

    return coordinate_decimal(confirmed.coordinates.longitude) == _quantised_decimal(
        activity.coordinates.longitude
    ) and coordinate_decimal(confirmed.coordinates.latitude) == _quantised_decimal(
        activity.coordinates.latitude
    )


def assess_cross_day_continuity(ctx: ValidationContext) -> RuleAssessment:
    """Every overnight bridge must match the skeleton accommodation.

    Single-day trips are N/A.  Without a skeleton, or when the skeleton
    dates do not match the itinerary, the bridge is UNKNOWN — never FAIL.
    AREA_ESTIMATED / UNRESOLVED overnights are UNKNOWN.  A CONFIRMED
    overnight requires matching ACCOMMODATION nodes on both sides; any
    mismatch makes the whole rule FAIL.
    """
    from trip_agent.planning.trip_skeleton import (
        AreaEstimatedAccommodation,
        UnresolvedAccommodation,
    )

    days = ctx.itinerary.days
    if len(days) <= 1:
        return RuleAssessment(
            result=_result(
                CROSS_RULE_ID,
                RuleOutcome.NOT_APPLICABLE,
                "SINGLE_DAY_TRIP",
                "single-day trips have no overnight bridges",
            )
        )
    skeleton = ctx.trip_skeleton
    if skeleton is None:
        return RuleAssessment(
            result=_result(
                CROSS_RULE_ID,
                RuleOutcome.UNKNOWN,
                "TRIP_SKELETON_UNAVAILABLE",
                "trip skeleton was not provided",
                affected_dates=_bounded_dates({day.date for day in days}),
            )
        )
    itinerary_dates = tuple(day.date for day in days)
    skeleton_dates = tuple(day.date for day in skeleton.days)
    if itinerary_dates != skeleton_dates:
        return RuleAssessment(
            result=_result(
                CROSS_RULE_ID,
                RuleOutcome.UNKNOWN,
                "TRIP_SKELETON_DATE_MISMATCH",
                "skeleton dates do not match itinerary dates",
                affected_dates=_bounded_dates({day.date for day in days}),
            )
        )

    findings: list[RuleFinding] = []
    fail_count = 0
    unknown_count = 0
    pass_count = 0
    affected_dates: set[date] = set()
    affected_refs: set[str] = set()

    for index, overnight in enumerate(skeleton.overnights):
        accommodation = overnight.accommodation
        from_day = days[index]
        to_day = days[index + 1]
        if isinstance(accommodation, AreaEstimatedAccommodation):
            unknown_count += 1
            affected_dates.update((overnight.from_date, overnight.to_date))
            findings.append(
                RuleFinding(
                    reason_code="ACCOMMODATION_AREA_ESTIMATED",
                    message=(
                        f"overnight {overnight.from_date} -> {overnight.to_date} is area-estimated"
                    ),
                    affected_date=overnight.from_date,
                )
            )
        elif isinstance(accommodation, UnresolvedAccommodation):
            unknown_count += 1
            affected_dates.update((overnight.from_date, overnight.to_date))
            findings.append(
                RuleFinding(
                    reason_code="ACCOMMODATION_UNRESOLVED",
                    message=(
                        f"overnight {overnight.from_date} -> {overnight.to_date} is unresolved"
                    ),
                    affected_date=overnight.from_date,
                )
            )
        else:
            last_from = from_day.activities[-1]
            first_to = to_day.activities[0]
            match = _confirmed_matches_activity(
                accommodation, last_from
            ) and _confirmed_matches_activity(accommodation, first_to)
            if match:
                pass_count += 1
            else:
                fail_count += 1
                affected_dates.update((overnight.from_date, overnight.to_date))
                if accommodation.provider_poi_id is not None:
                    affected_refs.add(accommodation.provider_poi_id)
                findings.append(
                    RuleFinding(
                        reason_code="OVERNIGHT_ENDPOINT_MISMATCH",
                        message=(
                            f"overnight {overnight.from_date} -> {overnight.to_date} "
                            "does not match the confirmed accommodation endpoints"
                        ),
                        affected_date=overnight.from_date,
                        affected_entity_refs=(
                            (accommodation.provider_poi_id,)
                            if accommodation.provider_poi_id is not None
                            else ()
                        ),
                    )
                )

    if fail_count > 0:
        outcome = RuleOutcome.FAIL
        reason_code = "OVERNIGHT_ENDPOINT_MISMATCH"
        message = f"{fail_count} confirmed overnight(s) have mismatched endpoints"
    elif unknown_count > 0:
        first_unknown = next(
            finding.reason_code
            for finding in findings
            if finding.reason_code
            in {
                "ACCOMMODATION_AREA_ESTIMATED",
                "ACCOMMODATION_UNRESOLVED",
            }
        )
        outcome = RuleOutcome.UNKNOWN
        reason_code = first_unknown
        message = f"{unknown_count} overnight(s) have unverifiable accommodation"
    else:
        outcome = RuleOutcome.PASS
        reason_code = "CROSS_DAY_ENDPOINTS_CONTINUOUS"
        message = "every overnight bridge matches its confirmed accommodation"
    return RuleAssessment(
        result=_result(
            CROSS_RULE_ID,
            outcome,
            reason_code,
            message,
            affected_dates=_bounded_dates(affected_dates),
            affected_entity_refs=_bounded_refs(affected_refs),
        ),
        findings=tuple(findings),
    )
