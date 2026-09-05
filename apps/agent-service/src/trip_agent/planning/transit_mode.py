"""B18-B: walking/driving transport-mode baseline — pure rules, no I/O.

The first version of the mode decision is deliberately narrow:

  a leg the traveller can plausibly walk within ``WALKING_THRESHOLD_SECONDS``
  should be WALKING; every other leg keeps the DRIVING road baseline.

This is NOT a best-mode recommender: public transit, taxi and self-driving
semantics belong to later phases.  ``DRIVING`` here only means "road
baseline", never "the user owns a car" (B18 design decision §4.7).

``WALKING_PREFILTER_METERS`` is an API cost optimisation ONLY — it decides
whether issuing a real WALKING route query is worth it.  It is calibrated
from real AMAP samples (B18 execution report §5) and must NOT
be read as "the user can only walk X metres".  The two thresholds answer
different questions:

- ``should_try_walking``  → cost: worth querying the walking API?
- ``is_walkable``         → product rule: walking is the right mode?
"""

from math import asin, cos, radians, sin, sqrt

from trip_agent.providers.errors import ProviderErrorCategory
from trip_agent.providers.map import Coordinates

# User-facing product rule: actual walking duration at or under 20 minutes is
# acceptable as the primary mode. Python is the sole AUTO recommendation
# authority; the web client only displays the persisted/current selection.
WALKING_THRESHOLD_SECONDS = 1200

# API cost prefilter, calibrated from real AMAP walking samples (623 m haversine
# → 218 s walk; 946 m haversine → 1696 s walk).  Haversine underestimates the
# real walking distance (~2x at the sampled distances), so a conservative,
# slightly larger prefilter is preferred: 宁多查, 不漏掉真实 ≤20min walking.
WALKING_PREFILTER_METERS = 1500

_EARTH_RADIUS_METERS = 6_371_008.8

# Failures that mean a mode is unavailable for this recommendation. Auth,
# permission, quota, malformed response and invalid request remain fatal.
RECOVERABLE_ROUTE_CATEGORIES = frozenset(
    {
        ProviderErrorCategory.TIMEOUT,
        ProviderErrorCategory.NETWORK_ERROR,
        ProviderErrorCategory.PROVIDER_UNAVAILABLE,
        ProviderErrorCategory.RATE_LIMITED,
        ProviderErrorCategory.NO_RESULT,
        ProviderErrorCategory.UNSUPPORTED_MODE,
    }
)


def straight_line_distance_meters(origin: Coordinates, destination: Coordinates) -> float:
    """Haversine straight-line distance in metres (pure, no I/O)."""
    latitude_delta = radians(destination.latitude - origin.latitude)
    longitude_delta = radians(destination.longitude - origin.longitude)
    origin_latitude = radians(origin.latitude)
    destination_latitude = radians(destination.latitude)
    haversine = sin(latitude_delta / 2) ** 2 + (
        cos(origin_latitude) * cos(destination_latitude) * sin(longitude_delta / 2) ** 2
    )
    angular_distance = 2 * asin(min(1.0, sqrt(haversine)))
    return _EARTH_RADIUS_METERS * angular_distance


def should_try_walking(straight_line_distance_m: float) -> bool:
    """Whether a real WALKING route query is worth issuing (cost only)."""
    return straight_line_distance_m <= WALKING_PREFILTER_METERS


def is_walkable(
    walking_duration_seconds: int,
    threshold_seconds: int = WALKING_THRESHOLD_SECONDS,
) -> bool:
    """Business rule: the actual walking duration fits the threshold.

    The threshold is context-dependent as of Planning Intelligence V1:
    weather-aware callers pass a tightened value derived from
    ``planning.weather_policy.walking_threshold_for``; callers without a
    weather context (e.g. the standalone route service) keep the 20-minute
    product default.
    """
    return walking_duration_seconds <= threshold_seconds
