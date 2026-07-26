"""Stable failure mapping for AMap route APIs.

Error-code frozensets are imported from ``trip_agent.infrastructure.amap.errors``
(the single source of truth, shared with the POI provider).
"""

from datetime import UTC, datetime
from time import perf_counter

from trip_agent.infrastructure.amap.errors import (
    AUTH_CODES,
    INVALID_REQUEST_CODES,
    QUOTA_CODES,
    RATE_CODES,
    UNAVAILABLE_CODES,
)
from trip_agent.providers.map import ProviderErrorCode, ProviderFailure


class AmapRouteFailures:

    @classmethod
    def from_http(cls, status_code: int, started_at: float) -> ProviderFailure:
        if status_code == 408:
            return cls.create(
                "PROVIDER_TIMEOUT",
                "AMap route request timed out",
                retryable=True,
                started_at=started_at,
            )
        if status_code in {401, 403}:
            return cls.create(
                "PROVIDER_AUTH_FAILED",
                "AMap route authentication failed",
                retryable=False,
                started_at=started_at,
            )
        if status_code == 429:
            return cls.create(
                "PROVIDER_RATE_LIMITED",
                "AMap route rate limit was reached",
                retryable=True,
                started_at=started_at,
            )
        if status_code >= 500:
            return cls.create(
                "PROVIDER_UNAVAILABLE",
                "AMap route service is temporarily unavailable",
                retryable=True,
                started_at=started_at,
            )
        return cls.create(
            "PROVIDER_ERROR",
            "AMap route request failed",
            retryable=False,
            started_at=started_at,
        )

    @classmethod
    def from_business(cls, infocode: str, started_at: float) -> ProviderFailure:
        if infocode in AUTH_CODES:
            return cls.create(
                "PROVIDER_AUTH_FAILED",
                "AMap route authentication failed",
                retryable=False,
                started_at=started_at,
            )
        if infocode in RATE_CODES:
            return cls.create(
                "PROVIDER_RATE_LIMITED",
                "AMap route rate limit was reached",
                retryable=True,
                started_at=started_at,
            )
        if infocode in QUOTA_CODES:
            return cls.create(
                "PROVIDER_QUOTA_EXHAUSTED",
                "AMap route quota was exhausted",
                retryable=False,
                started_at=started_at,
            )
        if infocode in UNAVAILABLE_CODES or infocode.startswith("3"):
            return cls.create(
                "PROVIDER_UNAVAILABLE",
                "AMap route service is temporarily unavailable",
                retryable=True,
                started_at=started_at,
            )
        if infocode in INVALID_REQUEST_CODES:
            return cls.create(
                "PROVIDER_REQUEST_INVALID",
                "AMap rejected the route request parameters",
                retryable=False,
                started_at=started_at,
            )
        return cls.create(
            "PROVIDER_ERROR",
            "AMap route service returned an error",
            retryable=False,
            started_at=started_at,
        )

    @staticmethod
    def create(
        error_code: ProviderErrorCode,
        error_message: str,
        *,
        retryable: bool,
        started_at: float,
    ) -> ProviderFailure:
        return ProviderFailure(
            provider="AMAP",
            error_code=error_code,
            error_message=error_message,
            retryable=retryable,
            latency_ms=AmapRouteFailures.elapsed_ms(started_at),
            fetched_at=datetime.now(UTC),
        )

    @staticmethod
    def elapsed_ms(started_at: float) -> int:
        return max(0, int((perf_counter() - started_at) * 1000))
