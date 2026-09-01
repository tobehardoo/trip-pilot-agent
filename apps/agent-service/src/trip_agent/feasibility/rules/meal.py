"""B5 — MEAL_WINDOW canonical rule.

Every explicit meal window applies to every itinerary day.  Meal type comes
exclusively from :class:`MealPlacementBinding` — titles are never guessed.
With a COMPLETE projection, any missing or out-of-window placement FAILs;
with an UNAVAILABLE projection the rule can only be UNKNOWN.
"""

from __future__ import annotations

from datetime import date

from trip_agent.domain.shared import CHINA_TIME_ZONE
from trip_agent.feasibility.context import ValidationContext
from trip_agent.feasibility.inputs import (
    ActivityLocator,
    MealPlacementBinding,
    MealProjectionState,
)
from trip_agent.feasibility.models import RuleOutcome, RuleResult
from trip_agent.feasibility.rules.core import (
    MAX_AFFECTED_DATES,
    RULE_VERSION,
    RuleAssessment,
    RuleFinding,
)

MEAL_RULE_ID = "MEAL_WINDOW"


def _seconds(value) -> float:
    """Exact local seconds-of-day (includes seconds and microseconds)."""
    return value.hour * 3600 + value.minute * 60 + value.second + value.microsecond / 1_000_000


def _result(
    outcome: RuleOutcome,
    reason_code: str,
    message: str,
    *,
    affected_dates: tuple[date, ...] = (),
) -> RuleResult:
    return RuleResult(
        rule_id=MEAL_RULE_ID,
        rule_version=RULE_VERSION,
        outcome=outcome,
        reason_code=reason_code,
        message=message,
        affected_dates=affected_dates,
    )


def assess_meal_window(ctx: ValidationContext) -> RuleAssessment:
    """Every explicit USER meal window must contain its placement each day.

    B13-F: only USER windows are hard constraints.  DEFAULT windows are soft
    suggestions (the scheduler still places them) and DISABLED windows are
    not projected — neither can FAIL this rule.
    """
    windows = tuple(
        window
        for window in ctx.command.payload.trip.constraints.meal_windows
        if getattr(window, "source", "USER") == "USER"
    )
    if not windows:
        return RuleAssessment(
            result=_result(
                RuleOutcome.NOT_APPLICABLE,
                "NO_MEAL_WINDOWS",
                "no user-configured meal windows constrain validation",
            )
        )
    inputs = ctx.validation_inputs
    if inputs is None or inputs.meal_projection_state is MealProjectionState.UNAVAILABLE:
        return RuleAssessment(
            result=_result(
                RuleOutcome.UNKNOWN,
                "MEAL_WINDOW_UNVERIFIED",
                "meal placement projection is unavailable",
            )
        )

    bindings_by_day: dict[int, dict[str, MealPlacementBinding]] = {}
    for binding in inputs.meal_placement_bindings:
        bindings_by_day.setdefault(binding.activity.day_index, {})[binding.meal_type.value] = (
            binding
        )
    # B13_FIX R3 (P0-3): days with untyped MEAL activities (Java-sourced
    # snapshots) cannot be verified by identity — never guess by position.
    unverified_days = set(inputs.unverified_meal_days)

    findings: list[RuleFinding] = []
    fail_count = 0
    unknown_count = 0
    pass_count = 0
    affected_dates: set[date] = set()

    for day_index, day in enumerate(ctx.itinerary.days):
        day_windows = {window.meal_type: window for window in windows}
        day_bindings = bindings_by_day.get(day_index, {})
        for meal_type, window in day_windows.items():
            binding = day_bindings.get(meal_type)
            if binding is None:
                if day_index in unverified_days:
                    unknown_count += 1
                    affected_dates.add(day.date)
                    findings.append(
                        RuleFinding(
                            reason_code="MEAL_WINDOW_UNVERIFIED",
                            message=(
                                f"day {day.date} {meal_type} placement cannot be verified "
                                "because the meal activity carries no meal type"
                            ),
                            affected_date=day.date,
                        )
                    )
                    continue
                fail_count += 1
                affected_dates.add(day.date)
                findings.append(
                    RuleFinding(
                        reason_code="MEAL_PLACEMENT_MISSING",
                        message=(
                            f"day {day.date} has no {meal_type} placement "
                            "for its explicit meal window"
                        ),
                        affected_date=day.date,
                    )
                )
                continue
            activity = day.activities[binding.activity.activity_index]
            start = activity.start_time
            end = activity.end_time
            if (
                start.tzinfo is None
                or end.tzinfo is None
                or start.utcoffset() is None
                or end.utcoffset() is None
            ):
                unknown_count += 1
                affected_dates.add(day.date)
                findings.append(
                    RuleFinding(
                        reason_code="MEAL_WINDOW_UNVERIFIED",
                        message=(
                            f"day {day.date} {meal_type} placement time is not timezone-aware"
                        ),
                        affected_date=day.date,
                        activity=ActivityLocator(day_index, binding.activity.activity_index),
                    )
                )
                continue
            local_start = start.astimezone(CHINA_TIME_ZONE)
            local_end = end.astimezone(CHINA_TIME_ZONE)
            if local_start.date() != day.date or local_end.date() != day.date:
                unknown_count += 1
                affected_dates.add(day.date)
                findings.append(
                    RuleFinding(
                        reason_code="MEAL_WINDOW_UNVERIFIED",
                        message=(
                            f"day {day.date} {meal_type} placement is not on the itinerary day"
                        ),
                        affected_date=day.date,
                        activity=ActivityLocator(day_index, binding.activity.activity_index),
                    )
                )
                continue
            inside = _seconds(local_start.time()) >= _seconds(window.start_time) and _seconds(
                local_end.time()
            ) <= _seconds(window.end_time)
            if inside:
                pass_count += 1
            else:
                fail_count += 1
                affected_dates.add(day.date)
                findings.append(
                    RuleFinding(
                        reason_code="MEAL_OUTSIDE_WINDOW",
                        message=(
                            f"day {day.date} {meal_type} placement is outside "
                            "its explicit meal window"
                        ),
                        affected_date=day.date,
                        activity=ActivityLocator(day_index, binding.activity.activity_index),
                    )
                )

    if fail_count > 0:
        outcome = RuleOutcome.FAIL
        reason_code = next(
            (
                finding.reason_code
                for finding in findings
                if finding.reason_code in {"MEAL_PLACEMENT_MISSING", "MEAL_OUTSIDE_WINDOW"}
            ),
            "MEAL_PLACEMENT_MISSING",
        )
        message = f"{fail_count} meal window(s) are not satisfied"
    elif unknown_count > 0:
        outcome = RuleOutcome.UNKNOWN
        reason_code = "MEAL_WINDOW_UNVERIFIED"
        message = f"{unknown_count} meal placement(s) are unverifiable"
    else:
        outcome = RuleOutcome.PASS
        reason_code = "MEAL_WINDOWS_VERIFIED"
        message = "every explicit meal window contains its placement"
    return RuleAssessment(
        result=_result(
            outcome,
            reason_code,
            message,
            affected_dates=tuple(sorted(affected_dates))[:MAX_AFFECTED_DATES],
        ),
        findings=tuple(findings),
    )
