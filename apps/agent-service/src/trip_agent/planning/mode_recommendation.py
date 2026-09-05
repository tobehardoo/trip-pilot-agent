"""B19-C: staged, ordered-rule multi-mode recommendation over real route facts.

Pure decision rules — no I/O.  The planner queries real WALKING / TRANSIT /
DRIVING routes and this module picks the mode from the resulting facts:

1. a leg that fits the walking threshold short-circuits to WALKING (the
   B18-B product rule: walkability wins even when a car would be faster —
   this is deliberately NOT a min(duration) recommender);
2. otherwise TRANSIT and DRIVING are compared on duration ratio, transfer
   burden and walking burden (ordered rules — TRANSIT is accepted only when
   all three burdens are acceptable);
3. provider failures are handled by the caller: recoverable failures make a
   candidate mode unavailable, non-recoverable failures keep raising.

Cost is intentionally NOT compared: TRANSIT cost is a fare while DRIVING
cost is an AMap toll estimate — different economic semantics (B19-A §6).
mobility accessibility only tightens the walking/transfer burdens (B19-C
plan §20); it never means "prefer taxi" or "always DRIVING".
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from trip_agent.providers._route_contracts import RoutePlan
    from trip_agent.providers.map import ProviderSuccess

# Every remaining leg must stay affordable for its baseline route query
# (the DRIVING road baseline) before any extra TRANSIT probe is allowed.
MIN_BASELINE_CALLS_PER_LEG = 1

# Calibrated from the B19-C Golden matrix (execution report §4/§5).  Values
# are injected in tests; these defaults are the production constants chosen
# by the calibration scan.
MAX_TRANSIT_DURATION_RATIO = 1.2
MAX_TRANSFERS = 2
MAX_TRANSIT_WALKING_METERS = 1_500
# Mobility-reduced travellers get stricter walking/transfer burdens.
REDUCED_MOBILITY_WALKING_MULTIPLIER = 0.5
REDUCED_MOBILITY_MAX_TRANSFERS = 1


class ModeRecommendationReason(StrEnum):
    WALKABLE = "WALKABLE"
    TRANSIT_FASTER_THAN_ROAD = "TRANSIT_FASTER_THAN_ROAD"
    TRANSIT_COMPETITIVE_LOW_TRANSFER = "TRANSIT_COMPETITIVE_LOW_TRANSFER"
    ROAD_SIGNIFICANTLY_FASTER = "ROAD_SIGNIFICANTLY_FASTER"
    TRANSIT_TOO_MANY_TRANSFERS = "TRANSIT_TOO_MANY_TRANSFERS"
    TRANSIT_EXCESSIVE_WALKING = "TRANSIT_EXCESSIVE_WALKING"
    TRANSIT_UNAVAILABLE = "TRANSIT_UNAVAILABLE"
    ROAD_UNAVAILABLE = "ROAD_UNAVAILABLE"
    BUDGET_DEGRADED = "BUDGET_DEGRADED"


@dataclass(frozen=True)
class ConsideredMode:
    mode: str
    available: bool
    duration_seconds: int | None = None
    distance_meters: int | None = None
    walking_distance_meters: int | None = None
    transfer_count: int | None = None
    cost: float | None = None


@dataclass(frozen=True)
class ModeRecommendation:
    """Result of the per-leg recommendation.

    ``selected_route`` enters the itinerary verbatim (single-source facts);
    ``reason`` and ``considered`` are for logging / tests / evaluation trace
    only — they are NOT persisted into the itinerary or the event contract.
    """

    selected_route: ProviderSuccess[RoutePlan]
    reason: ModeRecommendationReason
    considered: tuple[ConsideredMode, ...]


def can_probe_transit(remaining_budget: int, remaining_legs: int) -> bool:
    """Whether an extra TRANSIT probe is affordable for the current leg.

    Every remaining leg (including this one) must stay affordable for its
    baseline route query (``MIN_BASELINE_CALLS_PER_LEG``), and the probe
    itself costs one extra call.  The check is deliberately conservative:
    it assumes the probe is not cached (a cache hit only helps).

    This replaces the fixed ``BUDGET_DEGRADE_THRESHOLD=80`` from the early
    plan-c draft with a remaining-leg / remaining-call aware reservation.
    """
    minimum_reserved = remaining_legs * MIN_BASELINE_CALLS_PER_LEG
    return remaining_budget > minimum_reserved


def accessible_burdens(
    *,
    mobility_reduced: bool,
    max_transfers: int,
    max_transit_walking_meters: int,
) -> tuple[int, int]:
    """Burden thresholds, tightened for reduced-mobility travellers.

    Returns ``(transfer_limit, walking_limit)``.  REDUCED/STEP_FREE only
    lowers accessibility burdens — it never forces DRIVING or prefers taxi.
    """
    if not mobility_reduced:
        return max_transfers, max_transit_walking_meters
    return (
        min(max_transfers, REDUCED_MOBILITY_MAX_TRANSFERS),
        round(max_transit_walking_meters * REDUCED_MOBILITY_WALKING_MULTIPLIER),
    )


def decide_transit_or_road(
    transit_duration_seconds: int,
    road_duration_seconds: int,
    *,
    transfer_count: int | None,
    walking_distance_meters: int | None,
    max_transit_duration_ratio: float,
    max_transfers: int,
    max_transit_walking_meters: int,
) -> tuple[bool, ModeRecommendationReason]:
    """Ordered rules: choose TRANSIT only when every burden is acceptable.

    Missing transfer/walking facts (None) are treated as acceptable — the
    absence of evidence is not grounds for rejection.  Returns
    ``(choose_transit, reason)``.
    """
    if transit_duration_seconds > road_duration_seconds * max_transit_duration_ratio:
        return False, ModeRecommendationReason.ROAD_SIGNIFICANTLY_FASTER
    if transfer_count is not None and transfer_count > max_transfers:
        return False, ModeRecommendationReason.TRANSIT_TOO_MANY_TRANSFERS
    if (
        walking_distance_meters is not None
        and walking_distance_meters > max_transit_walking_meters
    ):
        return False, ModeRecommendationReason.TRANSIT_EXCESSIVE_WALKING
    if transit_duration_seconds <= road_duration_seconds:
        return True, ModeRecommendationReason.TRANSIT_FASTER_THAN_ROAD
    return True, ModeRecommendationReason.TRANSIT_COMPETITIVE_LOW_TRANSFER
