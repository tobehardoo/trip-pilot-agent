"""Pure, provider-agnostic daily schedule construction.

This module contains only deterministic business logic for turning trip
constraints and candidate activities into a structured daily plan.  It never
calls external map, route, or knowledge providers, and it never resolves real
POIs (including restaurants).  Provider adapters feed it resolved data and the
module returns a :class:`DayPlan` the provider then turns into an itinerary.

Scope for this round (B1):

* day-type classification (ARRIVAL_DAY / FULL_DAY / DEPARTURE_DAY /
  SPECIAL_ACTIVITY_DAY)
* daily time-window computation with default start/end (no fixed two-activity
  fallback when anchors are missing)
* fixed-time anchors (arrival / departure / fixed schedules / time-fixed
  activities) placed first, free windows computed around them
* capacity-driven activity selection keyed on activity magnitude
* meal *demand* generation (time window, recommended region, budget,
  preference) — not restaurant resolution
* buffer handling and last-resort trimming of optional activities

Meals are expressed as reservations of time in the day's capacity.  Whether a
real restaurant POI exists is resolved by the provider; the reservation stays
in the plan either way, so a provider failure never silently removes meal time.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace as _replace
from datetime import date, datetime, time
from decimal import Decimal
from typing import Literal

from trip_agent.domain.shared import (
    CHINA_TIME_ZONE,
    ActivityKind,
    DayType,
    Magnitude,
    MealType,
    Pace,
)
from trip_agent.planning.budget_policy import meal_budget_envelope
from trip_agent.planning.visit_duration import VisitDurationProfile

# Default daily window.  When arrival/departure are missing we do NOT fall back
# to a fixed two-activity model — the window is filled by capacity.
# 功能③（2026-09）：默认日终提到 21:00（RELAXED/BALANCED 可排晚间活动）；
# INTENSIVE 保持 20:00 紧凑。DINNER 仍锚定 18:00，晚间可继续排活动。
DEFAULT_DAY_START_MINUTE = 9 * 60
DEFAULT_DAY_END_MINUTE = 21 * 60
INTENSIVE_DAY_END_MINUTE = 20 * 60

# Representative durations by magnitude (minutes).
MAGNITUDE_DURATION_MINUTES: dict[Magnitude, int] = {
    "LIGHT": 90,
    "NORMAL": 150,
    "HALF_DAY": 240,
    "FULL_DAY": 480,
}

MEAL_DURATION_MINUTES = 60
ARRIVAL_BUFFER_MINUTES = 30
DEPARTURE_BUFFER_MINUTES = 60

# Space between consecutive items (transit + wayfinding slack), by pace.
BUFFER_BETWEEN_MINUTES: dict[Pace, int] = {
    "RELAXED": 20,
    "BALANCED": 12,
    "INTENSIVE": 8,
}

# V2 P1-A (audit AC-5): a relaxed day reserves deliberate slack inside every
# sightseeing slot — the same mechanism the mobility-reduced path uses with
# its 30-minute discount — so fewer activities fit and "想轻松一点" has a
# real, observable effect on the day's load (RELAXED ≡ BALANCED was the
# largest measured functional gap in the V2 audit).
RELAXED_SLOT_CAPACITY_DISCOUNT_MINUTES = 60

# Minimum free-window length that is worth scheduling anything into.
MIN_SLOT_MINUTES = 60

# Default meal placement (movable).  LUNCH anchors to 12:00, DINNER to 18:00.
DEFAULT_MEAL_MINUTE: dict[MealType, int] = {
    "LUNCH": 12 * 60,
    "DINNER": 18 * 60,
}


@dataclass(frozen=True, slots=True)
class TravelAnchor:
    """An arrival or departure anchor supplied by the user constraints."""

    kind: Literal["ARRIVAL", "DEPARTURE"]
    label: str
    at: datetime


@dataclass(frozen=True, slots=True)
class FixedSchedule:
    label: str
    start: datetime
    end: datetime


@dataclass(frozen=True, slots=True)
class OpeningAvailability:
    """Planning-domain opening constraint for one candidate on one day.

    B9.2 — derived exclusively from the resolver's VERIFIED_WINDOW /
    VERIFIED_CLOSED verdicts with ``hard_constraint_eligible=True``.  Any
    UNKNOWN/STALE/CONFLICTING/ineligible evidence maps to ``UNKNOWN`` and
    never constrains placement.  This type intentionally does not import the
    resolver or worker contracts.
    """

    kind: Literal["VERIFIED_WINDOW", "VERIFIED_CLOSED", "UNKNOWN"]
    windows: tuple[tuple[int, int], ...] = ()
    last_entry_minute: int | None = None

    @property
    def constrains_placement(self) -> bool:
        return self.kind == "VERIFIED_WINDOW"


def _time_to_minute(value: time) -> int:
    return value.hour * 60 + value.minute


def opening_availability_from_resolved(resolved: object) -> OpeningAvailability:
    """Map a resolver verdict onto the placement-domain constraint.

    Only VERIFIED_WINDOW / VERIFIED_CLOSED with ``hard_constraint_eligible``
    may constrain placement; every other state (UNKNOWN/STALE/CONFLICTING or
    ineligible evidence) maps to UNKNOWN and leaves the scheduler
    unconstrained.  Cross-midnight windows keep their close minute past 1440
    so the earliest-legal-window search never truncates them silently.
    """
    state = getattr(resolved, "state", None)
    if not getattr(resolved, "hard_constraint_eligible", False) or state not in {
        "VERIFIED_WINDOW",
        "VERIFIED_CLOSED",
    }:
        return OpeningAvailability(kind="UNKNOWN")
    if state == "VERIFIED_CLOSED":
        return OpeningAvailability(kind="VERIFIED_CLOSED")
    windows = tuple(
        (
            _time_to_minute(window.open),
            _time_to_minute(window.close) + window.close_day_offset * 1440,
        )
        for window in (getattr(resolved, "windows", None) or ())
    )
    last_entry = getattr(resolved, "last_entry", None)
    return OpeningAvailability(
        kind="VERIFIED_WINDOW",
        windows=windows,
        last_entry_minute=(_time_to_minute(last_entry) if last_entry is not None else None),
    )


@dataclass(frozen=True, slots=True)
class CandidateActivity:
    """A candidate placed into the schedule.

    ``time_fixed`` means the activity itself has a locked time window (an
    appointment).  Must-visit places are expressed with ``must_include`` and
    are NOT ``time_fixed`` — their time remains schedulable.
    """

    poi_id: str
    title: str
    magnitude: Magnitude
    coordinates: tuple[float, float] | None = None
    region: str | None = None
    must_include: bool = False
    time_fixed: bool = False
    fixed_start: datetime | None = None
    fixed_end: datetime | None = None
    kind: ActivityKind = "ATTRACTION"
    score: int = 0
    # B5: optional versioned duration profile.  When present, the scheduler
    # uses recommended_minutes; otherwise it falls back to the magnitude map.
    visit_duration_profile: VisitDurationProfile | None = None
    # B9.2: verified opening constraint; only VERIFIED eligible evidence
    # constrains placement, everything else is UNKNOWN and unconstrained.
    opening: OpeningAvailability | None = None


@dataclass(frozen=True, slots=True)
class MealWindowConstraint:
    """Planning-domain explicit meal window (B9.4, B13-F).

    Independent of worker contracts.  A cross-midnight window stores its
    end minute past 1440 so day-local comparison stays total and correct.
    ``source`` mirrors the worker contract: USER windows are hard (a meal
    must fit inside), DEFAULT windows are soft suggestions (a meal that does
    not fit falls back to the default minute), DISABLED windows suppress the
    meal entirely.  Historical source-less windows keep USER semantics.
    """

    meal_type: MealType
    start_minute: int
    end_minute: int
    source: Literal["DEFAULT", "USER", "DISABLED"] = "USER"


@dataclass(frozen=True, slots=True)
class MealDemand:
    """A reserved meal time slot that still needs a real restaurant POI."""

    meal_type: MealType
    start_minute: int
    end_minute: int
    region: str | None = None
    # V3 P2-1: per-meal, per-person SOFT budget envelope attached by
    # build_meal_demands (budget_per_person_per_day x MEAL_BUDGET_RATIO /
    # meals that day).  None when no budget was stated.  Soft: an overspend
    # never removes the meal, it only produces a BUDGET_CONSTRAINT trace.
    budget_per_person: Decimal | None = None
    preferences: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PlacedActivity:
    """A chosen activity with an explicit minute placement inside a slot."""

    candidate: CandidateActivity
    start_minute: int
    end_minute: int


@dataclass(frozen=True, slots=True)
class DayPlanItem:
    kind: ActivityKind | Literal["MEAL"]
    title: str
    start_minute: int
    end_minute: int
    poi_id: str | None = None
    time_fixed: bool = False
    magnitude: Magnitude | None = None
    region: str | None = None
    meal: MealDemand | None = None


@dataclass(frozen=True, slots=True)
class VirtualDayOrigin:
    """Internal day origin used when no real hotel was resolved.

    Never persisted and never rendered as a real hotel node.  Used only for
    capacity and transit-budget accounting.
    """

    label: str
    coordinates: tuple[float, float] | None
    accommodation_known: bool


@dataclass(frozen=True, slots=True)
class DayPlan:
    date: date
    day_type: DayType
    window_start_minute: int
    window_end_minute: int
    items: tuple[DayPlanItem, ...]
    meal_demands: tuple[MealDemand, ...]
    origin: VirtualDayOrigin | None
    accommodation_unknown: bool
    warnings: tuple[str, ...]
    # B4A: the day's dominant region, derived by the existing weighted
    # majority algorithm; None when no candidate/fixed item carries a
    # region.  Used by the transient AMap accommodation projection only.
    primary_region: str | None = None


def classify_day_type(
    trip_date: date,
    start_date: date,
    end_date: date,
    arrival: datetime | None,
    departure: datetime | None,
    *,
    has_full_day_experience: bool = False,
) -> DayType:
    """Determine the day type for a trip date.

    A day that is both the first and the last trip date is a single-day trip
    and is classified by how much usable time it has, never by a fixed
    template.
    """
    is_first = trip_date == start_date
    is_last = trip_date == end_date
    if is_first and is_last:
        start = _anchor_minute(arrival)
        end = _anchor_minute(departure)
        if start is not None and start >= 15 * 60:
            return "ARRIVAL_DAY"
        if end is not None and end <= 11 * 60:
            return "DEPARTURE_DAY"
        return "SPECIAL_ACTIVITY_DAY" if has_full_day_experience else "FULL_DAY"
    if is_first and arrival is not None:
        return "ARRIVAL_DAY"
    if is_last and departure is not None:
        return "DEPARTURE_DAY"
    return "SPECIAL_ACTIVITY_DAY" if has_full_day_experience else "FULL_DAY"


def day_window_minutes(
    trip_date: date,
    start_date: date,
    end_date: date,
    arrival: datetime | None,
    departure: datetime | None,
    *,
    pace: Pace = "BALANCED",
) -> tuple[int, int]:
    """Compute the usable minute window for a day.

    Defaults to 09:00–21:00 (INTENSIVE stays 20:00), tightened by
    arrival/departure on the first/last day.  Missing anchors keep the default
    window — the plan is still built by capacity.

    The window always keeps room for the anchor it carries: a late arrival
    (after the default end) still leaves the arrival buffer, and an early
    departure (before the default start) still leaves the departure buffer.
    This guarantees ARRIVAL/DEPARTURE anchor items are never dropped by a
    negative window.
    """
    start = DEFAULT_DAY_START_MINUTE
    end = DEFAULT_DAY_END_MINUTE if pace != "INTENSIVE" else INTENSIVE_DAY_END_MINUTE
    if trip_date == start_date and arrival is not None:
        start = max(start, _anchor_minute(arrival))
        # A late arrival must still fit: extend the end to cover arrival+buffer.
        end = max(end, start + ARRIVAL_BUFFER_MINUTES)
    if trip_date == end_date and departure is not None:
        end = min(end, _anchor_minute(departure))
        # An early departure must still fit: pull the start back to cover
        # buffer+departure.
        start = min(start, end - DEPARTURE_BUFFER_MINUTES)
    return start, end


def build_fixed_items(
    trip_date: date,
    arrival: datetime | None,
    departure: datetime | None,
    fixed_schedules: tuple[FixedSchedule, ...],
    time_fixed_activities: tuple[CandidateActivity, ...],
) -> tuple[DayPlanItem, ...]:
    """Build the ordered fixed-time anchors for a day.

    Only items whose window falls on ``trip_date`` are included.  Overlapping
    fixed items are surfaced via ``DayPlan.warnings``.
    """
    items: list[DayPlanItem] = []
    if arrival is not None and arrival.astimezone(CHINA_TIME_ZONE).date() == trip_date:
        start = _anchor_minute(arrival)
        items.append(
            DayPlanItem(
                kind="ARRIVAL",
                title="到达",
                start_minute=start,
                end_minute=start + ARRIVAL_BUFFER_MINUTES,
                time_fixed=True,
            )
        )
    for activity in time_fixed_activities:
        if activity.fixed_start is None or activity.fixed_end is None:
            continue
        items.append(
            DayPlanItem(
                kind=activity.kind,
                title=activity.title,
                start_minute=_to_minute(activity.fixed_start),
                end_minute=_to_minute(activity.fixed_end),
                poi_id=activity.poi_id,
                time_fixed=True,
                magnitude=activity.magnitude,
                region=activity.region,
            )
        )
    for schedule in fixed_schedules:
        items.append(
            DayPlanItem(
                kind="ATTRACTION",
                title=schedule.label,
                start_minute=_to_minute(schedule.start),
                end_minute=_to_minute(schedule.end),
                time_fixed=True,
            )
        )
    if departure is not None and departure.astimezone(CHINA_TIME_ZONE).date() == trip_date:
        end = _anchor_minute(departure)
        items.append(
            DayPlanItem(
                kind="DEPARTURE",
                title="离开",
                start_minute=end - DEPARTURE_BUFFER_MINUTES,
                end_minute=end,
                time_fixed=True,
            )
        )
    items.sort(key=lambda item: (item.start_minute, item.end_minute, item.title))
    return tuple(items)


def compute_free_windows(
    fixed_items: tuple[DayPlanItem, ...],
    window_start_minute: int,
    window_end_minute: int,
) -> tuple[tuple[int, int], ...]:
    """Return the free minute intervals between/around fixed items."""
    if window_end_minute <= window_start_minute:
        return ()
    bounds: list[tuple[int, int]] = [(window_start_minute, window_end_minute)]
    for item in fixed_items:
        start, end = item.start_minute, item.end_minute
        next_bounds: list[tuple[int, int]] = []
        for low, high in bounds:
            if end <= low or start >= high:
                next_bounds.append((low, high))
                continue
            if low < start:
                next_bounds.append((low, start))
            if end < high:
                next_bounds.append((end, high))
        bounds = next_bounds
    return tuple((low, high) for low, high in bounds if high - low >= MIN_SLOT_MINUTES)


def build_meal_demands(
    day_type: DayType,
    window_start_minute: int,
    window_end_minute: int,
    free_windows: tuple[tuple[int, int], ...],
    *,
    primary_region: str | None,
    preferences: tuple[str, ...] = (),
    budget_per_person: Decimal | None = None,
    pace: Pace = "BALANCED",
    explicit_windows: tuple[MealWindowConstraint, ...] = (),
) -> tuple[MealDemand, ...]:
    """Reserve meal time inside the day's capacity.

    Explicit meal windows take precedence over the default suggested
    minutes; the reservation is kept even if the provider later fails to
    resolve a real restaurant: it represents guaranteed eating time, not a
    booking.
    """
    demands: list[MealDemand] = []
    lunch = _meal_demand(
        "LUNCH",
        day_type,
        window_start_minute,
        window_end_minute,
        free_windows,
        primary_region,
        preferences,
        budget_per_person,
        explicit_windows=explicit_windows,
    )
    if lunch is not None:
        demands.append(lunch)
    dinner = _meal_demand(
        "DINNER",
        day_type,
        window_start_minute,
        window_end_minute,
        free_windows,
        primary_region,
        preferences,
        budget_per_person,
        explicit_windows=explicit_windows,
    )
    if dinner is not None:
        demands.append(dinner)
    # V3 P2-1: attach the soft per-meal dining envelope (per person) so the
    # meal resolver can reason about affordability.  Soft by design — an
    # overspend never removes a meal (a meal always happens).
    if budget_per_person is not None and demands:
        envelope = meal_budget_envelope(budget_per_person, len(demands))
        demands = [
            _replace(demand, budget_per_person=envelope) for demand in demands
        ]
    return tuple(demands)


def _fill_slots_dispatch(
    candidates: tuple[CandidateActivity, ...],
    slots: tuple[tuple[int, int], ...],
    *,
    day_type: DayType,
    pace: Pace,
    mobility_reduced: bool,
    primary_region: str | None,
) -> tuple[PlacedActivity, ...]:
    """Route the free-slot fill through the configured day scheduler.

    ``PLANNING_DAY_SCHEDULER`` (see ``cpsat_schedule``) selects GREEDY (the
    historical behavior), CPSAT (exact selection, greedy fallback), or SHADOW
    (greedy authoritative, CP-SAT comparison logged).  The import stays lazy so
    the default path never pulls in ortools.
    """
    from trip_agent.planning.cpsat_schedule import (
        choose_activities_cpsat,
        choose_activities_shadow,
        resolve_day_scheduler,
    )

    scheduler = resolve_day_scheduler()
    if scheduler == "GREEDY":
        return _fill_slots(
            candidates,
            slots,
            pace=pace,
            mobility_reduced=mobility_reduced,
            primary_region=primary_region,
        )
    handler = choose_activities_shadow if scheduler == "SHADOW" else choose_activities_cpsat
    return handler(
        candidates,
        slots,
        day_type=day_type,
        pace=pace,
        mobility_reduced=mobility_reduced,
        primary_region=primary_region,
    )


def choose_activities(
    candidates: tuple[CandidateActivity, ...],
    slots: tuple[tuple[int, int], ...],
    *,
    day_type: DayType,
    pace: Pace = "BALANCED",
    mobility_reduced: bool = False,
    primary_region: str | None = None,
) -> tuple[PlacedActivity, ...]:
    """Pick a capacity-fitting, region-coherent set of placed activities.

    Must-include activities are placed first.  Activities from the primary
    region are preferred to reduce cross-region hops.  Relaxed/mobility-reduced
    travellers get fewer items with more space.
    """
    movable = tuple(c for c in candidates if not c.time_fixed)
    if day_type == "SPECIAL_ACTIVITY_DAY":
        special_candidate = _choose_special_day(movable)
        if special_candidate is None or not slots:
            return _fill_slots_dispatch(
                movable,
                slots,
                day_type=day_type,
                pace=pace,
                mobility_reduced=mobility_reduced,
                primary_region=primary_region,
            )
        main_slot = slots[0]
        special = (_place(movable, special_candidate, main_slot[0]),)
        special_minutes = _total_minutes(special)
        remaining_slots = tuple(
            (low, high)
            for low, high in (
                (main_slot[0] + special_minutes, main_slot[1]),
                *slots[1:],
            )
            if high - low >= MIN_SLOT_MINUTES
        )
        extras = _fill_slots_dispatch(
            tuple(c for c in movable if c is not special_candidate),
            remaining_slots,
            day_type=day_type,
            pace=pace,
            mobility_reduced=mobility_reduced,
            primary_region=primary_region,
        )
        return (*special, *extras)

    return _fill_slots_dispatch(
        movable,
        slots,
        day_type=day_type,
        pace=pace,
        mobility_reduced=mobility_reduced,
        primary_region=primary_region,
    )


def plan_day(
    *,
    trip_date: date,
    start_date: date,
    end_date: date,
    arrival: datetime | None,
    departure: datetime | None,
    accommodation_known: bool,
    fixed_schedules: tuple[FixedSchedule, ...] = (),
    candidates: tuple[CandidateActivity, ...] = (),
    has_full_day_experience: bool = False,
    pace: Pace = "BALANCED",
    mobility_reduced: bool = False,
    meal_preferences: tuple[str, ...] = (),
    budget_per_person: Decimal | None = None,
    meal_windows: tuple[MealWindowConstraint, ...] = (),
    window_override: tuple[int, int] | None = None,
) -> DayPlan:
    """Build a full daily plan from constraints and candidates.

    The returned plan contains fixed anchors, chosen activities, and meal
    *demands*.  Real restaurant resolution and real route timing are left to
    the provider, which may re-space the items using actual transit durations.

    ``window_override`` is the B17 bounded-repair escape hatch: the provider
    passes an explicitly relaxed window only after its deterministic capacity
    repair is exhausted, and only for a system-default boundary (never a
    user-derived arrival/departure anchor).  ``None`` keeps the default
    ``day_window_minutes`` computation — every existing caller is unchanged.
    """
    day_type = classify_day_type(
        trip_date,
        start_date,
        end_date,
        arrival,
        departure,
        has_full_day_experience=has_full_day_experience,
    )
    if window_override is not None:
        window_start, window_end = window_override
    else:
        window_start, window_end = day_window_minutes(
            trip_date, start_date, end_date, arrival, departure, pace=pace
        )
    if window_end <= window_start:
        return DayPlan(
            date=trip_date,
            day_type=day_type,
            window_start_minute=window_start,
            window_end_minute=window_end,
            items=(),
            meal_demands=(),
            origin=None,
            accommodation_unknown=not accommodation_known,
            warnings=("NO_USABLE_DAY_WINDOW",),
            primary_region=None,
        )

    time_fixed = tuple(c for c in candidates if c.time_fixed)
    movable = tuple(c for c in candidates if not c.time_fixed)
    fixed_items = build_fixed_items(trip_date, arrival, departure, fixed_schedules, time_fixed)
    free_windows = compute_free_windows(fixed_items, window_start, window_end)

    primary_region = _primary_region(movable, fixed_items)
    special_candidate = _choose_special_day(movable) if day_type == "SPECIAL_ACTIVITY_DAY" else None
    # A FULL_DAY experience covers in-scenic dining, so no separate meal slots
    # are reserved on that day (avoids overlapping the main route).
    skip_meals = special_candidate is not None and special_candidate.magnitude == "FULL_DAY"
    meal_demands = (
        ()
        if skip_meals
        else build_meal_demands(
            day_type,
            window_start,
            window_end,
            free_windows,
            primary_region=primary_region,
            preferences=meal_preferences,
            budget_per_person=budget_per_person,
            pace=pace,
            explicit_windows=meal_windows,
        )
    )
    slots = _split_windows_by_meals(free_windows, meal_demands, BUFFER_BETWEEN_MINUTES[pace])

    placed = choose_activities(
        movable,
        slots,
        day_type=day_type,
        pace=pace,
        mobility_reduced=mobility_reduced,
        primary_region=primary_region,
    )

    items = _assemble_items(
        fixed_items,
        meal_demands,
        placed,
        pace=pace,
    )
    warnings = _build_warnings(fixed_items, movable, placed)
    # B9.4/B13-F: a USER meal window that ended up without its meal is a
    # real conflict — never silently dropped.  DEFAULT suggestions and
    # DISABLED meals are intentionally not conflicts.
    placed_meal_types = {meal.meal_type for meal in meal_demands}
    for meal_window in meal_windows:
        if (
            meal_window.source == "USER"
            and _meal_allowed(meal_window.meal_type, day_type)
            and meal_window.meal_type not in placed_meal_types
        ):
            warnings.append(f"MEAL_WINDOW_CONFLICT:{meal_window.meal_type}")

    origin = VirtualDayOrigin(
        label="酒店" if accommodation_known else "城市中心",
        coordinates=None,
        accommodation_known=accommodation_known,
    )
    return DayPlan(
        date=trip_date,
        day_type=day_type,
        window_start_minute=window_start,
        window_end_minute=window_end,
        items=items,
        meal_demands=meal_demands,
        origin=origin,
        accommodation_unknown=not accommodation_known,
        warnings=tuple(warnings),
        primary_region=primary_region,
    )


# -- internal helpers --------------------------------------------------------


def _anchor_minute(value: datetime | None) -> int | None:
    if value is None:
        return None
    local = value.astimezone(CHINA_TIME_ZONE)
    return local.hour * 60 + local.minute


def _to_minute(value: datetime) -> int:
    local = value.astimezone(CHINA_TIME_ZONE)
    return local.hour * 60 + local.minute


def _meal_allowed(meal_type: MealType, day_type: DayType) -> bool:
    if day_type == "FULL_DAY":
        return True
    if day_type == "SPECIAL_ACTIVITY_DAY":
        return True
    if day_type == "ARRIVAL_DAY":
        return meal_type == "DINNER"
    if day_type == "DEPARTURE_DAY":
        return meal_type == "LUNCH"
    return meal_type == "LUNCH"


def _meal_demand(
    meal_type: MealType,
    day_type: DayType,
    window_start: int,
    window_end: int,
    free_windows: tuple[tuple[int, int], ...],
    primary_region: str | None,
    preferences: tuple[str, ...],
    budget_per_person: Decimal | None,
    *,
    explicit_windows: tuple[MealWindowConstraint, ...] = (),
) -> MealDemand | None:
    if not _meal_allowed(meal_type, day_type):
        return None
    matching = tuple(window for window in explicit_windows if window.meal_type == meal_type)
    if any(window.source == "DISABLED" for window in matching):
        # B13-F: a disabled meal is intentionally not projected.
        return None
    hard = tuple(window for window in matching if window.source == "USER")
    if hard:
        # A hard window wins: the meal is placed inside it.  The earliest
        # window that still has room is used deterministically; if none fits,
        # the meal is dropped and the caller surfaces MEAL_WINDOW_CONFLICT.
        return _place_inside_windows(
            meal_type,
            hard,
            free_windows,
            primary_region,
            preferences,
            budget_per_person,
        )
    soft = tuple(window for window in matching if window.source == "DEFAULT")
    if soft:
        placed = _place_inside_windows(
            meal_type,
            soft,
            free_windows,
            primary_region,
            preferences,
            budget_per_person,
        )
        if placed is not None:
            return placed
        # A DEFAULT suggestion that does not fit is not a conflict: the meal
        # still happens at the default minute (soft suggestion).
    preferred = DEFAULT_MEAL_MINUTE[meal_type]
    target = _nearest_free_window(free_windows, preferred)
    if target is None:
        return None
    low, high = target
    start = max(low, preferred)
    if start + MEAL_DURATION_MINUTES > high:
        start = high - MEAL_DURATION_MINUTES
    if start < low or start + MEAL_DURATION_MINUTES > window_end:
        return None
    return MealDemand(
        meal_type=meal_type,
        start_minute=start,
        end_minute=start + MEAL_DURATION_MINUTES,
        region=primary_region,
        budget_per_person=budget_per_person,
        preferences=preferences,
    )


def _place_inside_windows(
    meal_type: MealType,
    windows: tuple[MealWindowConstraint, ...],
    free_windows: tuple[tuple[int, int], ...],
    primary_region: str | None,
    preferences: tuple[str, ...],
    budget_per_person: Decimal | None,
) -> MealDemand | None:
    """Place a meal inside the earliest explicit window that has room."""
    for explicit in sorted(windows, key=lambda w: (w.start_minute, w.end_minute)):
        target = _nearest_free_window(
            tuple(
                (max(low, explicit.start_minute), min(high, explicit.end_minute))
                for low, high in free_windows
                if high > explicit.start_minute and low < explicit.end_minute
            ),
            explicit.start_minute,
        )
        if target is None:
            continue
        low, high = target
        start = max(low, explicit.start_minute)
        if start + MEAL_DURATION_MINUTES > min(high, explicit.end_minute):
            continue
        return MealDemand(
            meal_type=meal_type,
            start_minute=start,
            end_minute=start + MEAL_DURATION_MINUTES,
            region=primary_region,
            budget_per_person=budget_per_person,
            preferences=preferences,
        )
    return None


def _nearest_free_window(
    free_windows: tuple[tuple[int, int], ...], minute: int
) -> tuple[int, int] | None:
    candidates = tuple(w for w in free_windows if w[1] - w[0] >= MEAL_DURATION_MINUTES)
    if not candidates:
        return None
    return min(candidates, key=lambda w: abs(w[0] - minute))


def _primary_region(
    movable: tuple[CandidateActivity, ...],
    fixed_items: tuple[DayPlanItem, ...],
) -> str | None:
    region_scores: dict[str, int] = {}
    for item in fixed_items:
        if item.region:
            region_scores[item.region] = region_scores.get(item.region, 0) + 2
    for activity in movable:
        if not activity.region:
            continue
        weight = 3 if activity.must_include else 1
        region_scores[activity.region] = region_scores.get(activity.region, 0) + weight
    if not region_scores:
        return None
    return max(region_scores, key=lambda key: (region_scores[key], key))


def _choose_special_day(
    candidates: tuple[CandidateActivity, ...],
) -> CandidateActivity | None:
    full = tuple(c for c in candidates if c.magnitude == "FULL_DAY")
    if full:
        return max(full, key=lambda c: (c.must_include, c.score, c.title))
    half = tuple(c for c in candidates if c.magnitude == "HALF_DAY")
    if half:
        return max(half, key=lambda c: (c.must_include, c.score, c.title))
    return None


def _activity_duration_minutes(candidate: CandidateActivity) -> int:
    """One shared duration source for placement.

    A candidate with a versioned profile uses its recommended duration;
    otherwise the magnitude map applies.  `_place` and `_fill_slots` both
    use this helper so the two paths can never disagree.
    """
    profile = candidate.visit_duration_profile
    if profile is not None:
        return profile.recommended_minutes
    return MAGNITUDE_DURATION_MINUTES[candidate.magnitude]


def _place(
    candidates: tuple[CandidateActivity, ...],
    candidate: CandidateActivity,
    start_minute: int,
) -> PlacedActivity:
    return PlacedActivity(
        candidate=candidate,
        start_minute=start_minute,
        end_minute=start_minute + _activity_duration_minutes(candidate),
    )


def _total_minutes(placed: tuple[PlacedActivity, ...]) -> int:
    return sum(placed_end.end_minute - placed_end.start_minute for placed_end in placed)


def _fill_slots(
    candidates: tuple[CandidateActivity, ...],
    slots: tuple[tuple[int, int], ...],
    *,
    pace: Pace,
    mobility_reduced: bool,
    primary_region: str | None,
) -> tuple[PlacedActivity, ...]:
    buffer = BUFFER_BETWEEN_MINUTES[pace]
    ordered = tuple(
        sorted(
            candidates,
            key=lambda c: (
                not c.must_include,
                c.region != primary_region,
                -c.score,
                c.title,
                c.poi_id,
            ),
        )
    )
    placed: list[PlacedActivity] = []
    for low, high in slots:
        capacity = high - low
        if capacity < MIN_SLOT_MINUTES:
            continue
        if mobility_reduced:
            capacity = max(MIN_SLOT_MINUTES, capacity - 30)
        if pace == "RELAXED":
            capacity = max(
                MIN_SLOT_MINUTES,
                capacity - RELAXED_SLOT_CAPACITY_DISCOUNT_MINUTES,
            )
        cursor = low
        for activity in ordered:
            if any(item.candidate is activity for item in placed):
                continue
            duration = _activity_duration_minutes(activity)
            needed = duration + (buffer if cursor > low else 0)
            if activity.opening is not None and activity.opening.constrains_placement:
                # VERIFIED_WINDOW: place inside the earliest legal window;
                # the last-entry bound caps the start minute.
                start = _earliest_opening_placement(activity, low, high, cursor, duration, buffer)
                if start is None:
                    continue
                placed.append(
                    PlacedActivity(
                        candidate=activity,
                        start_minute=start,
                        end_minute=start + duration,
                    )
                )
                cursor = start + duration + buffer
                if cursor >= high:
                    break
                continue
            if activity.opening is not None and activity.opening.kind == "VERIFIED_CLOSED":
                # A verified closure means the candidate cannot run on this
                # day; it is excluded rather than silently moved.
                continue
            if needed > capacity - (cursor - low):
                continue
            placed.append(
                PlacedActivity(
                    candidate=activity,
                    start_minute=cursor,
                    end_minute=cursor + duration,
                )
            )
            cursor += needed
            if cursor >= high:
                break
    return tuple(placed)


def _earliest_opening_placement(
    activity: CandidateActivity,
    slot_low: int,
    slot_high: int,
    cursor: int,
    duration: int,
    buffer: int,
) -> int | None:
    """Pick the earliest deterministic legal start for a VERIFIED_WINDOW candidate."""
    opening = activity.opening
    assert opening is not None and opening.constrains_placement
    start_cursor = max(cursor, slot_low)
    for window_low, window_high in sorted(opening.windows):
        candidate_start = max(start_cursor, window_low)
        last_entry = opening.last_entry_minute
        if last_entry is not None:
            candidate_start = min(candidate_start, last_entry)
        if candidate_start < window_low:
            candidate_start = window_low
        if last_entry is not None and candidate_start > last_entry:
            continue
        candidate_end = candidate_start + duration
        if candidate_end > window_high:
            continue
        if candidate_end > slot_high:
            continue
        return candidate_start
    return None


def _split_windows_by_meals(
    free_windows: tuple[tuple[int, int], ...],
    meal_demands: tuple[MealDemand, ...],
    buffer: int,
) -> tuple[tuple[int, int], ...]:
    del buffer
    spans = sorted((meal.start_minute, meal.end_minute) for meal in meal_demands)
    slots: list[tuple[int, int]] = []
    for low, high in free_windows:
        cursor = low
        for span_start, span_end in spans:
            if span_end <= cursor or span_start >= high:
                continue
            if span_start > cursor and span_start - cursor >= MIN_SLOT_MINUTES:
                slots.append((cursor, span_start))
            cursor = max(cursor, span_end)
            if cursor >= high:
                break
        if high - cursor >= MIN_SLOT_MINUTES:
            slots.append((cursor, high))
    return tuple(slots)


def _assemble_items(
    fixed_items: tuple[DayPlanItem, ...],
    meal_demands: tuple[MealDemand, ...],
    placed: tuple[PlacedActivity, ...],
    *,
    pace: Pace,
) -> tuple[DayPlanItem, ...]:
    buffer = BUFFER_BETWEEN_MINUTES[pace]
    items: list[DayPlanItem] = [
        *fixed_items,
        *(
            DayPlanItem(
                kind="MEAL",
                title="午餐" if meal.meal_type == "LUNCH" else "晚餐",
                start_minute=meal.start_minute,
                end_minute=meal.end_minute,
                region=meal.region,
                meal=meal,
            )
            for meal in meal_demands
        ),
        *(
            DayPlanItem(
                kind=item.candidate.kind,
                title=item.candidate.title,
                start_minute=item.start_minute,
                end_minute=item.end_minute,
                poi_id=item.candidate.poi_id,
                magnitude=item.candidate.magnitude,
                region=item.candidate.region,
            )
            for item in placed
        ),
    ]
    items.sort(key=lambda item: (item.start_minute, item.end_minute, item.title))
    # Enforce the minimum buffer between consecutive items by shifting only
    # non-fixed items forward.
    result: list[DayPlanItem] = []
    for item in items:
        if result and not item.time_fixed:
            previous_end = result[-1].end_minute
            gap = item.start_minute - previous_end
            if gap < buffer:
                shift = buffer - gap
                item = DayPlanItem(
                    kind=item.kind,
                    title=item.title,
                    start_minute=item.start_minute + shift,
                    end_minute=item.end_minute + shift,
                    poi_id=item.poi_id,
                    time_fixed=item.time_fixed,
                    magnitude=item.magnitude,
                    region=item.region,
                    meal=item.meal,
                )
        result.append(item)
    return tuple(result)


def _build_warnings(
    fixed_items: tuple[DayPlanItem, ...],
    movable: tuple[CandidateActivity, ...],
    placed: tuple[PlacedActivity, ...],
) -> list[str]:
    warnings: list[str] = []
    for previous, current in zip(fixed_items, fixed_items[1:], strict=False):
        if current.start_minute < previous.end_minute:
            warnings.append(f"FIXED_OVERLAP:{previous.title}:{current.title}")
    placed_ids = {item.candidate.poi_id for item in placed}
    missing = tuple(
        candidate
        for candidate in movable
        if candidate.must_include and candidate.poi_id not in placed_ids
    )
    for candidate in missing:
        if candidate.opening is not None and candidate.opening.kind == "VERIFIED_CLOSED":
            warnings.append(f"MUST_VISIT_CLOSED:{candidate.title}")
        else:
            warnings.append(f"MUST_VISIT_UNSCHEDULED:{candidate.title}")
    return warnings
