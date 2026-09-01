"""Context conflict resolution for transport (pure ordered rules, no LLM).

Budget, weather and mobility must not be decided in isolation.  They are
resolved HERE, once, into optimization parameters — the B19-C mode rules
then receive plain numbers and keep their existing semantics.

Ordered rules (first match wins):

| # | condition                                   | transit tolerance | reason |
|---|----------------------------------------------|-------------------|--------|
| 1 | reduced mobility + RAIN/STORM                 | widened           | MOBILITY_SAFETY |
| 2 | STORM                                         | widened           | WEATHER_SAFETY |
| 3 | budget TIGHT (incl. TIGHT + RAIN)             | widened           | BUDGET_CONSTRAINT |
| 4 | budget RELAXED + RAIN/STORM                   | narrowed          | COMFORT_ALLOWS_ROAD |
| 5 | default                                       | baseline          | DEFAULT |

Rule 3 encodes the deliberate product choice "budget beats comfort": rain
never upgrades a tight-budget trip to road transport.  Rule 4 is the
mirror: a comfortable budget in bad weather may ride instead of walk/bus.

Transit tolerance is expressed as the B19-C duration ratio rather than a
cost comparison, because TRANSIT fares and DRIVING tolls are not
economically comparable (B19-A §6).
"""

from dataclasses import dataclass
from typing import Literal

from trip_agent.planning.budget_policy import BudgetPressure
from trip_agent.planning.mode_recommendation import MAX_TRANSIT_DURATION_RATIO
from trip_agent.planning.weather_policy import WeatherLevel, walking_threshold_for

# Widened: accept TRANSIT even when road is meaningfully faster.
WIDENED_TRANSIT_DURATION_RATIO = 1.6
# Narrowed: only take TRANSIT when it is not slower than road — road/taxi is
# acceptable for this traveller in this context.
NARROWED_TRANSIT_DURATION_RATIO = 1.0

_ADVERSE_FOR_COMFORT = frozenset({"RAIN", "STORM"})
_ADVERSE_FOR_MOBILITY = frozenset({"RAIN", "STORM"})


@dataclass(frozen=True, slots=True)
class TransportStrategy:
    """Resolved transport parameters for one trip day."""

    walking_threshold_seconds: int
    max_transit_duration_ratio: float
    reason: Literal[
        "MOBILITY_SAFETY",
        "WEATHER_SAFETY",
        "FIXED_SCHEDULE_DEADLINE",
        "BUDGET_CONSTRAINT",
        "COMFORT_ALLOWS_ROAD",
        "DEFAULT",
    ]


# Context-free baseline: unchanged B19-C semantics (20-minute walk, baseline
# transit tolerance).  Callers without a resolved context keep it.
DEFAULT_TRANSPORT_STRATEGY = TransportStrategy(
    walking_threshold_seconds=walking_threshold_for(None),
    max_transit_duration_ratio=MAX_TRANSIT_DURATION_RATIO,
    reason="DEFAULT",
)


def resolve_transport_strategy(
    *,
    weather_level: WeatherLevel | None,
    budget_pressure: BudgetPressure | None,
    mobility_reduced: bool,
) -> TransportStrategy:
    """Resolve context into transport parameters.  Pure, deterministic."""
    threshold = walking_threshold_for(weather_level)
    if mobility_reduced and weather_level in _ADVERSE_FOR_MOBILITY:
        return TransportStrategy(threshold, WIDENED_TRANSIT_DURATION_RATIO, "MOBILITY_SAFETY")
    if weather_level == "STORM":
        return TransportStrategy(threshold, WIDENED_TRANSIT_DURATION_RATIO, "WEATHER_SAFETY")
    if budget_pressure == "TIGHT":
        return TransportStrategy(threshold, WIDENED_TRANSIT_DURATION_RATIO, "BUDGET_CONSTRAINT")
    if budget_pressure == "RELAXED" and weather_level in _ADVERSE_FOR_COMFORT:
        return TransportStrategy(threshold, NARROWED_TRANSIT_DURATION_RATIO, "COMFORT_ALLOWS_ROAD")
    return TransportStrategy(threshold, MAX_TRANSIT_DURATION_RATIO, "DEFAULT")


# V3 P2-2c: a fixed appointment's arrival certainty outranks budget comfort.
# Safety still outranks the deadline: MOBILITY_SAFETY / WEATHER_SAFETY keep
# their widened transit tolerance even on a deadline leg.
def deadline_strategy(strategy: TransportStrategy) -> TransportStrategy:
    """Narrow the transit tolerance to arrival-certainty for one leg.

    Applied per leg at the call site when the destination slot is a fixed
    appointment: TRANSIT is only acceptable when it is not slower than road
    (ratio 1.0) — a tight budget's widened tolerance must not turn the leg
    into a missed appointment.  Pure: returns a new strategy.
    """
    if strategy.reason in ("MOBILITY_SAFETY", "WEATHER_SAFETY"):
        return strategy
    return TransportStrategy(
        strategy.walking_threshold_seconds,
        NARROWED_TRANSIT_DURATION_RATIO,
        "FIXED_SCHEDULE_DEADLINE",
    )
