"""Shared AMap error-code classification for POI, route and transit providers.

Single source of truth for the AMap infocode frozensets used by
``providers/map.py`` (AmapMapProvider), ``providers/_amap_route_failures.py``
(AmapRouteFailures) and ``providers/_amap_transit_failures.py``
(AmapTransitFailures).

F-3a: moved up from ``infrastructure/amap/errors.py`` so the dependency
direction stays providers (contracts) <- infrastructure (adapters).  The
providers layer must never import from infrastructure.

Every value is a documented AMap v5 infocode string.
"""

from __future__ import annotations

from typing import Final

# Keys missing, invalid, expired, or disabled.
AUTH_CODES: Final[frozenset[str]] = frozenset(
    {
        "10001",
        "10002",
        "10005",
    }
)

# Valid credentials without permission for the requested product or platform.
PERMISSION_CODES: Final[frozenset[str]] = frozenset(
    {
        "10006",
        "10007",
        "10008",
        "10009",
        "10011",
        "10012",
        "10013",
        "10026",
        "10041",
        "20011",
    }
)

# QPS throttling – retryable after backoff.
RATE_CODES: Final[frozenset[str]] = frozenset(
    {"10004", "10014", "10015", "10016", "10019", "10020", "10021", "10029"}
)

# Daily / monthly quota exhausted – may recover after quota reset.
QUOTA_CODES: Final[frozenset[str]] = frozenset(
    {"10003", "10010", "10044", "10045", "40000", "40001", "40002", "40003"}
)

# Transient service-side unavailability.
UNAVAILABLE_CODES: Final[frozenset[str]] = frozenset({"10017"})

# Malformed request – retrying with the same parameters will always fail.
INVALID_REQUEST_CODES: Final[frozenset[str]] = frozenset(
    {"20000", "20001", "20002", "20012"}
)
