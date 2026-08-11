"""Deterministic SHA-256 fingerprint for an itinerary.

The fingerprint is a pure function of the itinerary's serialized content.
It must never depend on cwd, system timezone, locale or wall-clock time,
so it is safe to use as a report identity for a given plan.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from trip_agent.worker.contracts import Itinerary


def compute_itinerary_fingerprint(itinerary: Itinerary) -> str:
    """Return the 64-char lowercase hex SHA-256 of the itinerary.

    Serialization is locked: ``mode="json"`` (JSON-safe types),
    ``by_alias=True`` (camelCase field names), ``exclude_none=False``
    (explicit nulls kept), compact separators and UTF-8 output.
    """
    payload = itinerary.model_dump(
        mode="json",
        by_alias=True,
        exclude_none=False,
    )
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return digest
