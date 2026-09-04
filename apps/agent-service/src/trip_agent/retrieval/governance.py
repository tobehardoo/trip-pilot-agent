"""Per-document knowledge governance: claim type x source reliability eligibility.

This is the decision-enabling layer between *retrieval* and *planning*.  It
moves governance from "must be a registered acquisition source" to the
document's own metadata, while keeping the trust/freshness model intact:

- A community post may influence a *recommendation* but can never assert a
  factual attribute (opening hours / ticket price / reservation rule).
- Only OFFICIAL sources may back factual attributes, and only while fresh.
- Community / curated recommendation evidence is a *soft ranking signal* —
  its staleness lowers its influence (via ``guide_fact_bonus``) rather than
  silently hard-blocking the whole retrieval.

Nothing here fakes a source: reliability_level is stored per document at
import time; eligibility only maps it onto the claim it is allowed to support.

The freshness horizon mirrors ``evidence_fusion.FRESH_WINDOW_DAYS`` so ranking,
fusion and eligibility all agree on what "fresh" means.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Literal

# Freshness window shared with the L3 ranking tier (evidence_fusion).
FRESH_WINDOW_DAYS = 30

type ClaimType = Literal["FACTUAL_ATTRIBUTE", "RECOMMENDATION", "PREFERENCE"]
type ReliabilityLevel = Literal["OFFICIAL", "CURATED", "COMMUNITY"]

# Which claim types each reliability level may back.
# FACTUAL_ATTRIBUTE is exclusive to OFFICIAL — community/curated must never
# assert opening hours / prices / reservation rules (the "don't register
# community as regulation" rule).
_FACTUAL_ELIGIBLE = frozenset({"OFFICIAL"})
_RECOMMENDATION_ELIGIBLE = frozenset({"OFFICIAL", "CURATED", "COMMUNITY"})
_PREFERENCE_ELIGIBLE = frozenset({"CURATED", "COMMUNITY"})

_CLAIM_ALLOWED: dict[ClaimType, frozenset[str]] = {
    "FACTUAL_ATTRIBUTE": _FACTUAL_ELIGIBLE,
    "RECOMMENDATION": _RECOMMENDATION_ELIGIBLE,
    "PREFERENCE": _PREFERENCE_ELIGIBLE,
}

# Whether staleness hard-excludes the source on a given claim type.
# Factual attributes must be fresh; soft signals are only weakened.
_STALE_EXCLUDES: dict[ClaimType, bool] = {
    "FACTUAL_ATTRIBUTE": True,
    "RECOMMENDATION": False,
    "PREFERENCE": False,
}

_VALID_CLAIM_TYPES = frozenset(_CLAIM_ALLOWED)


def is_valid_claim_type(value: str) -> bool:
    return value in _VALID_CLAIM_TYPES


def maximally_permissive_claim_type(reliability: str) -> ClaimType:
    """The strongest claim a reliability level is allowed to back.

    Used as the default when a document does not declare an explicit claim
    type, so a reliable source never gets over-restricted by accident and a
    community source never silently becomes a factual authority.
    """
    if reliability == "OFFICIAL":
        return "FACTUAL_ATTRIBUTE"
    return "RECOMMENDATION"


def claim_allowed(claim_type: ClaimType, reliability: str) -> bool:
    """Whether a source of ``reliability`` may support ``claim_type``."""
    return reliability in _CLAIM_ALLOWED[claim_type]


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class DocumentEligibility:
    """The governance verdict for one retrieved knowledge citation."""

    claim_type: ClaimType
    reliability: str
    allowed: bool  # reliability is allowed to back this claim type
    fresh: bool  # within the freshness window
    expired: bool  # outside its validity window (valid_to passed)
    usable: bool  # allowed and (not stale-excluded by this claim type)
    stale_reason: str | None


def assess_document(
    *,
    claim_type: ClaimType,
    reliability: str,
    collected_at: datetime,
    valid_to: date | None = None,
    now: datetime | None = None,
) -> DocumentEligibility:
    """Govern one document/citation against its claim type.

    ``now`` is an explicit reference clock for determinism; ``None`` treats the
    document as fresh (no injected clock).
    """
    reference = _normalize_datetime(now or datetime.now(UTC))
    collected = _normalize_datetime(collected_at)

    allowed = claim_allowed(claim_type, reliability)
    stale_excludes = _STALE_EXCLUDES[claim_type]

    fresh = True
    age = reference - collected
    if age.total_seconds() >= 0:
        fresh = age.days <= FRESH_WINDOW_DAYS

    expired = valid_to is not None and reference.date() > valid_to

    if not allowed:
        usable = False
        reason = f"SOURCE_RELIABILITY_NOT_ALLOWED:{reliability}"
    elif expired:
        usable = False
        reason = "DOCUMENT_VALIDITY_EXPIRED"
    elif stale_excludes and not fresh:
        usable = False
        reason = "STALE_FACTUAL_SOURCE"
    else:
        usable = True
        reason = None
    return DocumentEligibility(
        claim_type=claim_type,
        reliability=reliability,
        allowed=allowed,
        fresh=fresh,
        expired=expired,
        usable=usable,
        stale_reason=reason,
    )