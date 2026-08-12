"""Canonical hard rules: pure, deterministic functions over ValidationContext.

Each ``assess_*`` function evaluates exactly one rule and returns exactly one
``RuleAssessment`` (one ``RuleResult`` plus immutable ``RuleFinding`` items).
Finding messages reproduce the legacy runtime texts verbatim, so the
evaluation-layer adapter can flatten them without duplicating judgement
logic.

Rules must never mutate their input and must never depend on clocks,
network, providers or global mutable state.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from unicodedata import normalize

from trip_agent.domain.shared import CHINA_TIME_ZONE
from trip_agent.feasibility.context import ValidationContext
from trip_agent.feasibility.entity_refs import encode_poi_ref
from trip_agent.feasibility.models import RuleOutcome, RuleResult
from trip_agent.worker.contracts import FixedSchedule, ItineraryActivity

RULE_VERSION = "hard-rule-v1"

# Aggregate fields are bounded so oversized inputs stay reportable and
# deterministic: findings may grow without limit, the RuleResult aggregates
# may not.
MAX_AFFECTED_DATES = 16
MAX_AFFECTED_ENTITY_REFS = 64

# Structural anchors may repeat; attractions and experiences must not.
_REPEATABLE_KINDS = frozenset({"ACCOMMODATION", "ARRIVAL", "DEPARTURE", "MEAL"})


@dataclass(frozen=True, slots=True)
class RuleFinding:
    """One concrete violation (or observation) with a stable reason code."""

    reason_code: str
    message: str
    affected_date: date | None = None
    affected_entity_refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RuleAssessment:
    """The full outcome of one rule evaluation."""

    result: RuleResult
    findings: tuple[RuleFinding, ...] = ()


def _normalise_place_name(value: str) -> str:
    return "".join(
        character for character in normalize("NFKC", value).casefold() if character.isalnum()
    )


def activity_covers_fixed_schedule(
    activity: ItineraryActivity,
    schedule: FixedSchedule,
) -> bool:
    """Return whether an activity represents the scheduled place and window."""
    return (
        _normalise_place_name(activity.title) == _normalise_place_name(schedule.place_name)
        and activity.start_time <= schedule.start_time
        and activity.end_time >= schedule.end_time
    )


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


# ── TRIP_DATE_RANGE ──────────────────────────────────────────────────────


def assess_trip_date_range(ctx: ValidationContext) -> RuleAssessment:
    """Every itinerary day must fall inside the command's trip window."""
    trip_start = ctx.command.payload.trip.start_date
    trip_end = ctx.command.payload.trip.end_date
    findings: list[RuleFinding] = []
    outside_dates: set[date] = set()
    for day in ctx.itinerary.days:
        if day.date < trip_start or day.date > trip_end:
            outside_dates.add(day.date)
            findings.append(
                RuleFinding(
                    reason_code="DAY_OUTSIDE_TRIP_RANGE",
                    message=f"day {day.date} is outside trip range",
                    affected_date=day.date,
                )
            )
    if not findings:
        return RuleAssessment(
            result=_result(
                "TRIP_DATE_RANGE",
                RuleOutcome.PASS,
                "ALL_DAYS_WITHIN_TRIP_RANGE",
                "all itinerary days fall within the trip date range",
            )
        )
    return RuleAssessment(
        result=_result(
            "TRIP_DATE_RANGE",
            RuleOutcome.FAIL,
            "DAY_OUTSIDE_TRIP_RANGE",
            findings[0].message,
            affected_dates=tuple(sorted(outside_dates))[:MAX_AFFECTED_DATES],
        ),
        findings=tuple(findings),
    )


# ── FIXED_SCHEDULE_COVERAGE ──────────────────────────────────────────────


def assess_fixed_schedule_coverage(ctx: ValidationContext) -> RuleAssessment:
    """Every fixed schedule must be covered by a matching activity window."""
    schedules = ctx.command.payload.trip.constraints.fixed_schedules
    if not schedules:
        return RuleAssessment(
            result=_result(
                "FIXED_SCHEDULE_COVERAGE",
                RuleOutcome.NOT_APPLICABLE,
                "NO_FIXED_SCHEDULES",
                "no fixed schedules were provided",
            )
        )
    findings: list[RuleFinding] = []
    affected_dates: set[date] = set()
    for schedule in schedules:
        covered = any(
            activity_covers_fixed_schedule(activity, schedule)
            for day in ctx.itinerary.days
            for activity in day.activities
        )
        if not covered:
            schedule_date = schedule.start_time.astimezone(CHINA_TIME_ZONE).date()
            affected_dates.add(schedule_date)
            findings.append(
                RuleFinding(
                    reason_code="FIXED_SCHEDULE_NOT_COVERED",
                    message=f"fixed schedule '{schedule.place_name}' is not covered",
                    affected_date=schedule_date,
                )
            )
    if not findings:
        return RuleAssessment(
            result=_result(
                "FIXED_SCHEDULE_COVERAGE",
                RuleOutcome.PASS,
                "ALL_FIXED_SCHEDULES_COVERED",
                "every fixed schedule is covered by an activity window",
            )
        )
    return RuleAssessment(
        result=_result(
            "FIXED_SCHEDULE_COVERAGE",
            RuleOutcome.FAIL,
            "FIXED_SCHEDULE_NOT_COVERED",
            findings[0].message,
            affected_dates=tuple(sorted(affected_dates))[:MAX_AFFECTED_DATES],
        ),
        findings=tuple(findings),
    )


# ── BUDGET_LIMIT ─────────────────────────────────────────────────────────


def assess_budget_limit(ctx: ValidationContext) -> RuleAssessment:
    """Estimated cost must not exceed the user's budget amount."""
    ratio = ctx.budget.budget_ratio
    if ratio is None:
        return RuleAssessment(
            result=_result(
                "BUDGET_LIMIT",
                RuleOutcome.NOT_APPLICABLE,
                "BUDGET_NOT_SPECIFIED",
                "no budget amount was specified",
            )
        )
    if ratio <= 1.0:
        return RuleAssessment(
            result=_result(
                "BUDGET_LIMIT",
                RuleOutcome.PASS,
                "WITHIN_BUDGET",
                "estimated cost is within the budget",
            )
        )
    message = f"estimated cost exceeds budget by {round((ratio - 1) * 100)}%"
    finding = RuleFinding(
        reason_code="BUDGET_EXCEEDED",
        message=message,
    )
    return RuleAssessment(
        result=_result(
            "BUDGET_LIMIT",
            RuleOutcome.FAIL,
            "BUDGET_EXCEEDED",
            message,
        ),
        findings=(finding,),
    )


# ── DUPLICATE_POI ────────────────────────────────────────────────────────


def assess_duplicate_poi(ctx: ValidationContext) -> RuleAssessment:
    """A provider POI is a trip-wide identity; non-repeatable kinds may not
    appear more than once."""
    seen_poi_ids: set[str] = set()
    findings: list[RuleFinding] = []
    affected_dates: set[date] = set()
    for day in ctx.itinerary.days:
        for activity in day.activities:
            poi_id = activity.provider_poi_id
            if poi_id is None or activity.kind in _REPEATABLE_KINDS:
                continue
            if poi_id in seen_poi_ids:
                affected_dates.add(day.date)
                findings.append(
                    RuleFinding(
                        reason_code="DUPLICATE_POI",
                        message=f"duplicate POI '{poi_id}' appears more than once",
                        affected_date=day.date,
                        affected_entity_refs=(encode_poi_ref(poi_id),),
                    )
                )
            else:
                seen_poi_ids.add(poi_id)
    if not findings:
        return RuleAssessment(
            result=_result(
                "DUPLICATE_POI",
                RuleOutcome.PASS,
                "NO_DUPLICATE_POI",
                "no provider POI is scheduled more than once",
            )
        )
    refs = tuple(
        sorted(
            {
                finding.affected_entity_refs[0]
                for finding in findings
                if finding.affected_entity_refs
            }
        )
    )[:MAX_AFFECTED_ENTITY_REFS]
    return RuleAssessment(
        result=_result(
            "DUPLICATE_POI",
            RuleOutcome.FAIL,
            "DUPLICATE_POI",
            findings[0].message,
            affected_dates=tuple(sorted(affected_dates))[:MAX_AFFECTED_DATES],
            affected_entity_refs=refs,
        ),
        findings=tuple(findings),
    )


# ── ACTIVITY_OVERLAP ─────────────────────────────────────────────────────


def assess_activity_overlap(ctx: ValidationContext) -> RuleAssessment:
    """Activities on the same day may not overlap in time.  Detection is
    complete — every overlapping pair is reported, including nested
    intervals that adjacent-pair scanning would miss — and order-stable:
    activities are sorted by (start, end) before a single active-interval
    scan.  Equal end/start boundaries are not an overlap."""
    findings: list[RuleFinding] = []
    affected_dates: set[date] = set()
    for day in ctx.itinerary.days:
        activities = sorted(
            day.activities,
            key=lambda activity: (activity.start_time, activity.end_time),
        )
        active: list[ItineraryActivity] = []
        for current in activities:
            # Expire intervals that ended at or before the current start;
            # they cannot overlap this or any later activity.
            active = [previous for previous in active if previous.end_time > current.start_time]
            for previous in active:
                affected_dates.add(day.date)
                findings.append(
                    RuleFinding(
                        reason_code="ACTIVITY_OVERLAP",
                        message=(f"activities '{previous.title}' and '{current.title}' overlap"),
                        affected_date=day.date,
                    )
                )
            active.append(current)
    if not findings:
        return RuleAssessment(
            result=_result(
                "ACTIVITY_OVERLAP",
                RuleOutcome.PASS,
                "NO_ACTIVITY_OVERLAP",
                "no two activities overlap in time",
            )
        )
    return RuleAssessment(
        result=_result(
            "ACTIVITY_OVERLAP",
            RuleOutcome.FAIL,
            "ACTIVITY_OVERLAP",
            findings[0].message,
            affected_dates=tuple(sorted(affected_dates))[:MAX_AFFECTED_DATES],
        ),
        findings=tuple(findings),
    )
