"""Pure, deterministic repair planning and local candidate transformations."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from unicodedata import normalize

from trip_agent.domain.shared import CHINA_TIME_ZONE
from trip_agent.feasibility.entity_refs import encode_activity_ref, encode_poi_ref
from trip_agent.feasibility.inputs import (
    ActivityLocator,
    ValidationInputs,
)
from trip_agent.feasibility.repair.catalog import (
    RepairActionCode,
    RepairActionSpec,
    repair_action_for,
)
from trip_agent.feasibility.validator import ValidationRun
from trip_agent.guide_intelligence.opening_resolver import resolve_opening_hours
from trip_agent.worker.contracts import (
    Itinerary,
    ItineraryActivity,
    ItineraryDay,
    TransitLeg,
)

MAX_REPAIR_ATTEMPTS = 3
MAX_ACTIONS_PER_ATTEMPT = 16
MAX_REPAIR_DATES = 3


@dataclass(frozen=True, slots=True)
class RepairAction:
    code: RepairActionCode
    rule_id: str
    reason_code: str
    affected_date: date
    activity: ActivityLocator | None = None
    affected_entity_refs: tuple[str, ...] = ()
    requires_provider: bool = False


@dataclass(frozen=True, slots=True)
class RepairPlan:
    attempt_index: int
    actions: tuple[RepairAction, ...]

    def __post_init__(self) -> None:
        if self.attempt_index < 1 or self.attempt_index > MAX_REPAIR_ATTEMPTS:
            raise ValueError(f"attempt_index must be between 1 and {MAX_REPAIR_ATTEMPTS}")
        if not self.actions or len(self.actions) > MAX_ACTIONS_PER_ATTEMPT:
            raise ValueError("repair plan must contain between 1 and 16 actions")


@dataclass(frozen=True, slots=True)
class RepairCandidate:
    itinerary: Itinerary
    validation_inputs: ValidationInputs | None
    trip_skeleton: object | None


@dataclass(frozen=True, slots=True)
class AppliedRepair:
    candidate: RepairCandidate
    provider_dates: tuple[date, ...]


def plan_repairs(run: ValidationRun, *, attempt_index: int) -> RepairPlan | None:
    """Build a stable, bounded plan from canonical repairable FAIL findings."""
    if attempt_index < 1 or attempt_index > MAX_REPAIR_ATTEMPTS:
        return None
    actions: list[RepairAction] = []
    for assessment in run.assessments:
        result = assessment.result
        if not result.repairable:
            continue
        spec = repair_action_for(result.rule_id, result.outcome, result.reason_code)
        if spec is None:
            continue
        if spec.code is RepairActionCode.REMOVE_DUPLICATE_OPTIONAL_POI:
            actions.extend(_duplicate_actions(run, spec))
        elif spec.code is RepairActionCode.REFRESH_TRANSIT_LEGS:
            actions.extend(_provider_actions(assessment.findings, result.rule_id, spec))
        else:
            actions.extend(_located_actions(run, assessment.findings, result.rule_id, spec))
        if len(actions) >= MAX_ACTIONS_PER_ATTEMPT:
            break
    bounded = tuple(actions[:MAX_ACTIONS_PER_ATTEMPT])
    return RepairPlan(attempt_index=attempt_index, actions=bounded) if bounded else None


def _located_actions(run, findings, rule_id: str, spec: RepairActionSpec) -> list[RepairAction]:
    actions: list[RepairAction] = []
    for finding in findings:
        locator = finding.activity
        if finding.reason_code not in spec.reason_codes or locator is None:
            continue
        activity = run.itinerary.days[locator.day_index].activities[locator.activity_index]
        if _is_fixed(run, activity):
            continue
        day_date = run.itinerary.days[locator.day_index].date
        ref = _activity_ref(activity)
        actions.append(
            RepairAction(
                code=spec.code,
                rule_id=rule_id,
                reason_code=finding.reason_code,
                affected_date=day_date,
                activity=locator,
                affected_entity_refs=(ref,) if ref is not None else (),
                requires_provider=spec.requires_provider,
            )
        )
    return actions


def _provider_actions(findings, rule_id: str, spec: RepairActionSpec) -> list[RepairAction]:
    dates = sorted(
        {
            finding.affected_date
            for finding in findings
            if finding.reason_code in spec.reason_codes and finding.affected_date is not None
        }
    )[:MAX_REPAIR_DATES]
    return [
        RepairAction(
            code=spec.code,
            rule_id=rule_id,
            reason_code=spec.reason_codes[0],
            affected_date=day_date,
            requires_provider=True,
        )
        for day_date in dates
    ]


def _duplicate_actions(run: ValidationRun, spec: RepairActionSpec) -> list[RepairAction]:
    must_visit = {
        _normalise(value)
        for value in run.context.command.payload.trip.constraints.must_visit_places
    }
    seen: set[str] = set()
    actions: list[RepairAction] = []
    for day_index, day in enumerate(run.itinerary.days):
        for activity_index, activity in enumerate(day.activities):
            poi_id = activity.provider_poi_id
            if poi_id is None or activity.kind in {
                "ACCOMMODATION",
                "ARRIVAL",
                "DEPARTURE",
                "MEAL",
            }:
                continue
            if poi_id not in seen:
                seen.add(poi_id)
                continue
            if (
                activity_index in {0, len(day.activities) - 1}
                or _is_fixed(run, activity)
                or _normalise(activity.title) in must_visit
            ):
                continue
            locator = ActivityLocator(day_index, activity_index)
            actions.append(
                RepairAction(
                    code=spec.code,
                    rule_id="DUPLICATE_POI",
                    reason_code="DUPLICATE_POI",
                    affected_date=day.date,
                    activity=locator,
                    affected_entity_refs=(encode_poi_ref(poi_id),),
                    requires_provider=True,
                )
            )
    return actions


def apply_repair_plan(run: ValidationRun, plan: RepairPlan) -> AppliedRepair:
    """Apply local actions to an immutable candidate and return provider dates."""
    days = list(run.itinerary.days)
    provider_dates = {action.affected_date for action in plan.actions if action.requires_provider}
    for action in plan.actions:
        if action.code in {
            RepairActionCode.SHIFT_ACTIVITY_TO_OPENING_WINDOW,
            RepairActionCode.SHIFT_ACTIVITY_BEFORE_LAST_ENTRY,
        }:
            days = _apply_opening(run, days, action)
        elif action.code is RepairActionCode.CLAMP_VISIT_DURATION:
            days = _apply_duration(run, days, action)
        elif action.code is RepairActionCode.SHIFT_MEAL_TO_WINDOW:
            days = _apply_meal(run, days, action)

    inputs = run.context.validation_inputs
    removals = tuple(
        action.activity
        for action in plan.actions
        if action.code is RepairActionCode.REMOVE_DUPLICATE_OPTIONAL_POI
        and action.activity is not None
    )
    if removals:
        days, inputs = _remove_activities(days, inputs, removals)

    changed = tuple(days) != run.itinerary.days
    estimated_total_cost = (
        max(
            Decimal("0"),
            run.itinerary.estimated_total_cost - _removed_activity_cost(run, removals),
        )
        if removals
        else run.itinerary.estimated_total_cost
    )
    itinerary = (
        run.itinerary.model_copy(
            update={
                "days": tuple(days),
                "estimated_total_cost": estimated_total_cost,
            }
        )
        if changed
        else run.itinerary
    )
    return AppliedRepair(
        candidate=RepairCandidate(
            itinerary=itinerary,
            validation_inputs=inputs,
            trip_skeleton=run.context.trip_skeleton,
        ),
        provider_dates=tuple(sorted(provider_dates))[:MAX_REPAIR_DATES],
    )


def _apply_duration(run, days: list[ItineraryDay], action: RepairAction) -> list[ItineraryDay]:
    locator = action.activity
    if locator is None or run.context.validation_inputs is None:
        return days
    binding = next(
        (
            item
            for item in run.context.validation_inputs.visit_duration_bindings
            if item.activity == locator
        ),
        None,
    )
    if binding is None or not binding.profile.hard_constraint_eligible:
        return days
    activity = days[locator.day_index].activities[locator.activity_index]
    minutes = (
        binding.profile.min_minutes
        if action.reason_code == "VISIT_TOO_SHORT"
        else binding.profile.max_minutes
    )
    candidate = activity.model_copy(
        update={"end_time": activity.start_time + timedelta(minutes=minutes)}
    )
    if not _preserves_day_span(
        day=days[locator.day_index].date,
        original=activity,
        candidate=candidate,
    ):
        return days
    if not _fits_neighbors(days[locator.day_index], locator.activity_index, candidate):
        return days
    if not _fits_bound_opening(run, locator, candidate):
        return days
    return _replace_activity(days, locator, candidate)


def _apply_opening(run, days: list[ItineraryDay], action: RepairAction) -> list[ItineraryDay]:
    locator = action.activity
    if locator is None or run.context.validation_inputs is None:
        return days
    binding = next(
        (
            item
            for item in run.context.validation_inputs.opening_hours_bindings
            if item.activity == locator
        ),
        None,
    )
    if binding is None or run.context.validation_time is None:
        return days
    day = days[locator.day_index]
    activity = day.activities[locator.activity_index]
    resolved = resolve_opening_hours(
        binding.evidences,
        poi_key=binding.poi_key,
        trip_date=day.date,
        resolver_as_of=run.context.validation_time,
    )
    if (
        resolved.state != "VERIFIED_WINDOW"
        or not resolved.hard_constraint_eligible
        or resolved.closed
        or not resolved.windows
    ):
        return days
    duration = activity.end_time - activity.start_time
    if (
        action.code is RepairActionCode.SHIFT_ACTIVITY_BEFORE_LAST_ENTRY
        and resolved.last_entry is None
    ):
        return days
    for window in sorted(
        resolved.windows,
        key=lambda item: (item.open, item.close, item.close_day_offset),
    ):
        earliest = _local_datetime(day.date, window.open)
        latest = (
            _local_datetime(day.date, window.close)
            + timedelta(days=window.close_day_offset)
            - duration
        )
        if resolved.last_entry is not None:
            latest = min(latest, _local_datetime(day.date, resolved.last_entry))
        start = _earliest_neighbor_compatible_start(
            day,
            locator.activity_index,
            duration,
            earliest=earliest,
            latest=latest,
        )
        if start is None:
            continue
        candidate = activity.model_copy(update={"start_time": start, "end_time": start + duration})
        if not _preserves_day_span(day=day.date, original=activity, candidate=candidate):
            continue
        if _fits_neighbors(day, locator.activity_index, candidate) and _fits_bound_opening(
            run, locator, candidate
        ):
            return _replace_activity(days, locator, candidate)
    return days


def _apply_meal(run, days: list[ItineraryDay], action: RepairAction) -> list[ItineraryDay]:
    locator = action.activity
    if locator is None or run.context.validation_inputs is None:
        return days
    binding = next(
        (
            item
            for item in run.context.validation_inputs.meal_placement_bindings
            if item.activity == locator
        ),
        None,
    )
    if binding is None:
        return days
    window = next(
        (
            item
            for item in run.context.command.payload.trip.constraints.meal_windows
            if item.meal_type == binding.meal_type.value
        ),
        None,
    )
    if window is None:
        return days
    day = days[locator.day_index]
    activity = day.activities[locator.activity_index]
    duration = activity.end_time - activity.start_time
    start = _earliest_neighbor_compatible_start(
        day,
        locator.activity_index,
        duration,
        earliest=_local_datetime(day.date, window.start_time),
        latest=_local_datetime(day.date, window.end_time) - duration,
    )
    if start is None:
        return days
    candidate = activity.model_copy(update={"start_time": start, "end_time": start + duration})
    if not _preserves_day_span(day=day.date, original=activity, candidate=candidate):
        return days
    if candidate.end_time > _local_datetime(day.date, window.end_time):
        return days
    if not _fits_neighbors(day, locator.activity_index, candidate):
        return days
    return _replace_activity(days, locator, candidate)


def _earliest_neighbor_compatible_start(
    day: ItineraryDay,
    index: int,
    duration: timedelta,
    *,
    earliest: datetime,
    latest: datetime,
) -> datetime | None:
    incoming = next((leg for leg in day.transit_legs if leg.to_activity_index == index), None)
    outgoing = next((leg for leg in day.transit_legs if leg.from_activity_index == index), None)
    if index > 0:
        previous = day.activities[index - 1]
        earliest = max(
            earliest,
            previous.end_time + timedelta(seconds=incoming.duration_seconds if incoming else 0),
        )
    if index + 1 < len(day.activities):
        following = day.activities[index + 1]
        latest = min(
            latest,
            following.start_time
            - timedelta(seconds=outgoing.duration_seconds if outgoing else 0)
            - duration,
        )
    return earliest if earliest <= latest else None


def _fits_bound_opening(
    run: ValidationRun,
    locator: ActivityLocator,
    candidate: ItineraryActivity,
) -> bool:
    inputs = run.context.validation_inputs
    if inputs is None or run.context.validation_time is None:
        return True
    binding = next(
        (item for item in inputs.opening_hours_bindings if item.activity == locator),
        None,
    )
    if binding is None:
        return True
    day_date = run.itinerary.days[locator.day_index].date
    resolved = resolve_opening_hours(
        binding.evidences,
        poi_key=binding.poi_key,
        trip_date=day_date,
        resolver_as_of=run.context.validation_time,
    )
    if resolved.state != "VERIFIED_WINDOW" or not resolved.hard_constraint_eligible:
        return True
    if resolved.closed:
        return False
    if resolved.all_day:
        return True
    if not resolved.windows:
        return False
    start = candidate.start_time.astimezone(CHINA_TIME_ZONE)
    end = candidate.end_time.astimezone(CHINA_TIME_ZONE)
    if start.date() != day_date:
        return False
    for window in resolved.windows:
        opened = _local_datetime(day_date, window.open)
        closed = _local_datetime(day_date, window.close) + timedelta(days=window.close_day_offset)
        if opened <= start and end <= closed:
            return resolved.last_entry is None or start <= _local_datetime(
                day_date, resolved.last_entry
            )
    return False


def _fits_neighbors(day: ItineraryDay, index: int, candidate: ItineraryActivity) -> bool:
    incoming = next((leg for leg in day.transit_legs if leg.to_activity_index == index), None)
    outgoing = next((leg for leg in day.transit_legs if leg.from_activity_index == index), None)
    if index > 0:
        previous = day.activities[index - 1]
        required = timedelta(seconds=incoming.duration_seconds if incoming else 0)
        if previous.end_time + required > candidate.start_time:
            return False
    if index + 1 < len(day.activities):
        following = day.activities[index + 1]
        required = timedelta(seconds=outgoing.duration_seconds if outgoing else 0)
        if candidate.end_time + required > following.start_time:
            return False
    return True


def _preserves_day_span(
    *,
    day: date,
    original: ItineraryActivity,
    candidate: ItineraryActivity,
) -> bool:
    """Keep a repair within the same local-day span as the original activity."""
    original_span = (
        (original.start_time.astimezone(CHINA_TIME_ZONE).date() - day).days,
        (original.end_time.astimezone(CHINA_TIME_ZONE).date() - day).days,
    )
    candidate_span = (
        (candidate.start_time.astimezone(CHINA_TIME_ZONE).date() - day).days,
        (candidate.end_time.astimezone(CHINA_TIME_ZONE).date() - day).days,
    )
    return candidate_span == original_span


def _replace_activity(
    days: list[ItineraryDay], locator: ActivityLocator, activity: ItineraryActivity
) -> list[ItineraryDay]:
    updated = list(days)
    day = updated[locator.day_index]
    activities = list(day.activities)
    activities[locator.activity_index] = activity
    updated[locator.day_index] = day.model_copy(update={"activities": tuple(activities)})
    return updated


def _remove_activities(
    days: list[ItineraryDay],
    inputs: ValidationInputs | None,
    removals: tuple[ActivityLocator, ...],
) -> tuple[list[ItineraryDay], ValidationInputs | None]:
    by_day: dict[int, set[int]] = {}
    for locator in removals:
        by_day.setdefault(locator.day_index, set()).add(locator.activity_index)
    updated = list(days)
    for day_index, removed in by_day.items():
        day = updated[day_index]
        mapping = {
            old: new
            for new, old in enumerate(
                index for index in range(len(day.activities)) if index not in removed
            )
        }
        activities = tuple(
            activity for index, activity in enumerate(day.activities) if index not in removed
        )
        legs: list[TransitLeg] = []
        for leg in day.transit_legs:
            if (
                leg.from_activity_index in removed
                or leg.to_activity_index in removed
                or leg.from_activity_index not in mapping
                or leg.to_activity_index not in mapping
            ):
                continue
            new_from = mapping[leg.from_activity_index]
            new_to = mapping[leg.to_activity_index]
            if new_to != new_from + 1:
                continue
            legs.append(
                leg.model_copy(
                    update={
                        "from_activity_index": new_from,
                        "to_activity_index": new_to,
                    }
                )
            )
        updated[day_index] = day.model_copy(
            update={"activities": activities, "transit_legs": tuple(legs)}
        )
    return updated, _remap_inputs(inputs, by_day)


def _remap_inputs(
    inputs: ValidationInputs | None,
    removed_by_day: dict[int, set[int]],
) -> ValidationInputs | None:
    if inputs is None:
        return None

    def remap(locator: ActivityLocator) -> ActivityLocator | None:
        removed = removed_by_day.get(locator.day_index, set())
        if locator.activity_index in removed:
            return None
        shift = sum(1 for index in removed if index < locator.activity_index)
        return ActivityLocator(locator.day_index, locator.activity_index - shift)

    def mapped(bindings):
        result = []
        for binding in bindings:
            locator = remap(binding.activity)
            if locator is not None:
                result.append(replace(binding, activity=locator))
        return tuple(result)

    return ValidationInputs(
        opening_hours_bindings=mapped(inputs.opening_hours_bindings),
        visit_duration_bindings=mapped(inputs.visit_duration_bindings),
        meal_placement_bindings=mapped(inputs.meal_placement_bindings),
        meal_projection_state=inputs.meal_projection_state,
    )


def _activity_ref(activity: ItineraryActivity) -> str | None:
    if activity.activity_id is not None:
        return encode_activity_ref(activity.activity_id)
    if activity.provider_poi_id is not None:
        return encode_poi_ref(activity.provider_poi_id)
    return None


def _is_fixed(run: ValidationRun, activity: ItineraryActivity) -> bool:
    if activity.time_fixed is True:
        return True
    from trip_agent.feasibility.rules.core import activity_covers_fixed_schedule

    return any(
        activity_covers_fixed_schedule(activity, schedule)
        for schedule in run.context.command.payload.trip.constraints.fixed_schedules
    )


def _normalise(value: str) -> str:
    return "".join(
        character for character in normalize("NFKC", value).casefold() if character.isalnum()
    )


def _local_datetime(day_date: date, value: time) -> datetime:
    return datetime.combine(day_date, value, tzinfo=CHINA_TIME_ZONE)


def _removed_activity_cost(
    run: ValidationRun,
    removals: tuple[ActivityLocator, ...],
) -> Decimal:
    return sum(
        (
            run.itinerary.days[locator.day_index].activities[locator.activity_index].estimated_cost
            for locator in removals
        ),
        start=Decimal("0"),
    )
