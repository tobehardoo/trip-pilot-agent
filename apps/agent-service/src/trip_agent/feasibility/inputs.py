"""B5 — transient validation inputs for the standalone hard validator.

These immutable, read-only value objects carry the evidence and placement
facts the four new rules need (opening hours, visit duration, meal
placement) without reaching into provider infrastructure.  They exist only
inside ``PlanningResult`` memory objects; worker, messaging, DB and API
never consume them.

Locator correctness (day/activity indices, kind matches, POI ownership) is
enforced by :class:`ValidationContext` at construction; missing bindings
are evidence gaps that rules report as UNKNOWN, never construction errors.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from trip_agent.guide_intelligence.opening_evidence import OpeningHoursEvidence
    from trip_agent.planning.visit_duration import VisitDurationProfile

MAX_BINDINGS_PER_CATEGORY = 512


class MealWindowType(StrEnum):
    """Explicit meal window kinds a user may constrain."""

    BREAKFAST = "BREAKFAST"
    LUNCH = "LUNCH"
    DINNER = "DINNER"


class MealProjectionState(StrEnum):
    """Whether meal placement bindings are complete for the itinerary."""

    UNAVAILABLE = "UNAVAILABLE"
    COMPLETE = "COMPLETE"


@dataclass(frozen=True, slots=True)
class ActivityLocator:
    """Zero-based pointer into ``itinerary.days[day_index].activities``."""

    day_index: int
    activity_index: int

    def __post_init__(self) -> None:
        for value in (self.day_index, self.activity_index):
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError("locator indices must be integers, not booleans")
            if value < 0:
                raise ValueError("locator indices must be non-negative")


@dataclass(frozen=True, slots=True)
class OpeningHoursBinding:
    """Opening-hours evidence for one itinerary activity."""

    activity: ActivityLocator
    poi_key: str
    evidences: tuple[OpeningHoursEvidence, ...]

    def __post_init__(self) -> None:
        if isinstance(self.poi_key, str):
            object.__setattr__(self, "poi_key", self.poi_key.strip())
        if not self.poi_key:
            raise ValueError("poi_key must not be empty")
        object.__setattr__(self, "evidences", tuple(self.evidences))
        for evidence in self.evidences:
            if evidence.poi_key != self.poi_key:
                raise ValueError("evidence poi_key must match the binding poi_key")


@dataclass(frozen=True, slots=True)
class VisitDurationBinding:
    """A duration profile bound to one itinerary activity."""

    activity: ActivityLocator
    profile: VisitDurationProfile


@dataclass(frozen=True, slots=True)
class MealPlacementBinding:
    """A meal-type placement bound to one itinerary MEAL activity."""

    activity: ActivityLocator
    meal_type: MealWindowType

    def __post_init__(self) -> None:
        if not isinstance(self.meal_type, MealWindowType):
            raise TypeError("meal_type must be a MealWindowType instance")


@dataclass(frozen=True, slots=True)
class ValidationInputs:
    """Aggregated transient inputs for the validator (all snapshotted)."""

    opening_hours_bindings: tuple[OpeningHoursBinding, ...] = ()
    visit_duration_bindings: tuple[VisitDurationBinding, ...] = ()
    meal_placement_bindings: tuple[MealPlacementBinding, ...] = ()
    meal_projection_state: MealProjectionState = MealProjectionState.UNAVAILABLE
    # B13_FIX R3 (P0-3): days whose MEAL activities carry no explicit meal
    # type (Java-sourced replan/candidate snapshots).  Bindings for those
    # days can never be produced by identity, so the meal rule must report
    # UNKNOWN instead of a hard FAIL/PASS conclusion.
    unverified_meal_days: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "opening_hours_bindings", tuple(self.opening_hours_bindings))
        object.__setattr__(self, "visit_duration_bindings", tuple(self.visit_duration_bindings))
        object.__setattr__(self, "meal_placement_bindings", tuple(self.meal_placement_bindings))
        object.__setattr__(self, "unverified_meal_days", tuple(self.unverified_meal_days))
        if not isinstance(self.meal_projection_state, MealProjectionState):
            raise TypeError("meal_projection_state must be a MealProjectionState instance")
        for value in self.unverified_meal_days:
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError("unverified_meal_days entries must be integers, not booleans")
            if value < 0:
                raise ValueError("unverified_meal_days entries must be non-negative")
        for label, bindings in (
            ("opening_hours_bindings", self.opening_hours_bindings),
            ("visit_duration_bindings", self.visit_duration_bindings),
            ("meal_placement_bindings", self.meal_placement_bindings),
        ):
            if len(bindings) > MAX_BINDINGS_PER_CATEGORY:
                raise ValueError(f"{label} exceeds {MAX_BINDINGS_PER_CATEGORY} entries")
            locators = [binding.activity for binding in bindings]
            if len({locator for locator in locators}) != len(locators):
                raise ValueError(f"{label} must not repeat an activity locator")
        meal_keys = [
            (binding.activity.day_index, binding.meal_type)
            for binding in self.meal_placement_bindings
        ]
        if len(set(meal_keys)) != len(meal_keys):
            raise ValueError("meal placements must not repeat a day/meal-type pair")
