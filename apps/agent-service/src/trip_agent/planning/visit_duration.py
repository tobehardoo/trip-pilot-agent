"""B5 — Visit Duration Profile: the versioned, sourced duration model.

A profile expresses how long a visit should take (min / recommended / max)
plus where the numbers came from and whether they may drive hard
constraints.  Only PROVIDER or OFFICIAL_FACT profiles with sufficient
confidence may be hard-constraint eligible; category and system defaults
are planning guidance and can only ever produce UNKNOWN in the hard rule.

Invariants enforced at construction: frozen/slots, bool rejection,
``1 <= min <= recommended <= max <= 1440``, finite confidence in [0, 1],
real enum source (no silent string coercion), bounded non-empty
``source_ref`` / ``profile_version``, and the eligibility rules above.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import isfinite

# Hard-constraint eligibility requires at least this confidence.
HARD_ELIGIBLE_CONFIDENCE = 0.8


class DurationProfileSource(StrEnum):
    """Where a duration claim comes from."""

    PROVIDER = "PROVIDER"
    OFFICIAL_FACT = "OFFICIAL_FACT"
    CATEGORY_PROFILE = "CATEGORY_PROFILE"
    CATEGORY_FALLBACK = "CATEGORY_FALLBACK"
    SYSTEM_DEFAULT = "SYSTEM_DEFAULT"


_HARD_ELIGIBLE_SOURCES = frozenset(
    {DurationProfileSource.PROVIDER, DurationProfileSource.OFFICIAL_FACT}
)
_CATEGORY_SOURCES = frozenset(
    {
        DurationProfileSource.CATEGORY_PROFILE,
        DurationProfileSource.CATEGORY_FALLBACK,
        DurationProfileSource.SYSTEM_DEFAULT,
    }
)

MAX_PROFILE_MINUTES = 1440


def _bound_text(value: str, field: str) -> str:
    normalised = value.strip()
    if not normalised:
        raise ValueError(f"{field} must not be empty")
    if len(normalised) > 200:
        raise ValueError(f"{field} must be at most 200 characters")
    return normalised


@dataclass(frozen=True, slots=True)
class VisitDurationProfile:
    """Versioned visit-duration guidance with explicit provenance."""

    min_minutes: int
    recommended_minutes: int
    max_minutes: int
    source: DurationProfileSource
    source_ref: str
    confidence: float
    profile_version: str
    hard_constraint_eligible: bool = False

    def __post_init__(self) -> None:
        for value in (self.min_minutes, self.recommended_minutes, self.max_minutes):
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError("duration minutes must be integers, not booleans")
        if not 1 <= self.min_minutes <= self.recommended_minutes <= self.max_minutes:
            raise ValueError("durations must satisfy 1 <= min <= recommended <= max")
        if self.max_minutes > MAX_PROFILE_MINUTES:
            raise ValueError("duration minutes must not exceed 1440")
        if isinstance(self.confidence, bool) or not isinstance(self.confidence, float):
            raise TypeError("confidence must be a float, not a boolean")
        if not isfinite(self.confidence) or not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be finite and within [0, 1]")
        if not isinstance(self.source, DurationProfileSource):
            raise TypeError("source must be a DurationProfileSource instance")
        object.__setattr__(self, "source_ref", _bound_text(self.source_ref, "source_ref"))
        object.__setattr__(
            self, "profile_version", _bound_text(self.profile_version, "profile_version")
        )
        if self.source in _CATEGORY_SOURCES and self.hard_constraint_eligible:
            raise ValueError(
                "category and system-default profiles can never be hard-constraint eligible"
            )
        if self.hard_constraint_eligible and self.source not in _HARD_ELIGIBLE_SOURCES:
            raise ValueError(
                "only PROVIDER or OFFICIAL_FACT profiles can be hard-constraint eligible"
            )
        if self.hard_constraint_eligible and self.confidence < HARD_ELIGIBLE_CONFIDENCE:
            raise ValueError(
                f"hard-constraint eligible profiles need confidence >= {HARD_ELIGIBLE_CONFIDENCE}"
            )
