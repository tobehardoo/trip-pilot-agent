"""Deterministic weather → walking-policy mapping (pure, no I/O).

V1 Planning Intelligence: weather finally becomes a decision consumer.
The chain is deliberately narrow and testable:

    weather statements (per trip date)
        → WeatherLevel (most severe signal wins)
        → walking threshold (seconds)
        → transit_mode.is_walkable(duration, threshold)
        → per-leg mode decision

This is NOT "rain → taxi".  The threshold only decides when a leg stays
walkable; the ordered B19-C rules still pick between TRANSIT and DRIVING
afterwards.  No LLM, no provider calls.
"""

from typing import Literal

from trip_agent.planning.transit_mode import WALKING_THRESHOLD_SECONDS

type WeatherLevel = Literal["CLEAR", "OVERCAST", "DRIZZLE", "RAIN", "STORM"]

# Severity terms are checked in strict order: STORM first, then DRIZZLE
# (must precede RAIN — "小雨" contains "雨"), then RAIN, then overcast,
# then clear.  The first matching tier wins.
_STORM_TERMS = ("特大暴雨", "大暴雨", "暴雨", "台风", "雷暴", "冰雹", "沙尘暴")
_DRIZZLE_TERMS = ("小雨", "毛毛雨", "零星小雨", "light rain", "drizzle")
_RAIN_TERMS = ("雨", "rain", "shower", "降水")
_OVERCAST_TERMS = ("阴", "多云", "overcast", "cloudy")
_CLEAR_TERMS = ("晴", "clear", "sunny")

# Walking thresholds by weather level.  CLEAR/OVERCAST keep the historical
# 20-minute product rule; rain tiers tighten it stepwise.
WALKING_THRESHOLD_BY_WEATHER: dict[WeatherLevel, int] = {
    "CLEAR": WALKING_THRESHOLD_SECONDS,
    "OVERCAST": WALKING_THRESHOLD_SECONDS,
    "DRIZZLE": 900,
    "RAIN": 600,
    "STORM": 300,
}


def classify_weather_level(statements: tuple[str, ...] | str) -> WeatherLevel | None:
    """Return the most severe weather level found, or None when unknown.

    ``None`` means "no usable weather signal" — callers keep the product
    default walking threshold.  Unknown must never read as clear.
    """
    if isinstance(statements, str):
        statements = (statements,)
    lowered = " ".join(statements).casefold()
    if not lowered.strip():
        return None
    for terms, level in (
        (_STORM_TERMS, "STORM"),
        (_DRIZZLE_TERMS, "DRIZZLE"),
        (_RAIN_TERMS, "RAIN"),
        (_OVERCAST_TERMS, "OVERCAST"),
        (_CLEAR_TERMS, "CLEAR"),
    ):
        if any(term in lowered for term in terms):
            return level
    return None


def walking_threshold_for(level: WeatherLevel | None) -> int:
    """Resolve the walking threshold; unknown keeps the product default."""
    if level is None:
        return WALKING_THRESHOLD_SECONDS
    return WALKING_THRESHOLD_BY_WEATHER[level]
