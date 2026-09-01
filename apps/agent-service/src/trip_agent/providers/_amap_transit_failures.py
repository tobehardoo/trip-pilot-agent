"""Stable failure mapping for the AMap v3 transit API.

Error-code frozensets are imported from ``trip_agent.infrastructure.amap.errors``
(the single source of truth, shared with the POI and route providers).
"""

from datetime import UTC, datetime
from time import perf_counter

from trip_agent.infrastructure.amap.errors import (
    AUTH_CODES,
    INVALID_REQUEST_CODES,
    PERMISSION_CODES,
    QUOTA_CODES,
    RATE_CODES,
    UNAVAILABLE_CODES,
)
from trip_agent.providers.errors import (
    ProviderErrorCategory,
    ProviderOperation,
    category_for_error_code,
)
from trip_agent.providers.map import ProviderErrorCode, ProviderFailure


class AmapTransitFailures:

    @classmethod
    def from_http(
        cls,
        status_code: int,
        started_at: float,
        *,
        retry_after_seconds: float | None = None,
    ) -> ProviderFailure:
        safe_code = f"HTTP_{status_code}"
        if status_code == 408:
            return cls.create(
                "PROVIDER_TIMEOUT",
                "AMap transit request timed out",
                retryable=True,
                started_at=started_at,
                safe_provider_code=safe_code,
            )
        if status_code == 401:
            return cls.create(
                "PROVIDER_AUTH_FAILED",
                "AMap transit authentication failed",
                retryable=False,
                started_at=started_at,
                safe_provider_code=safe_code,
            )
        if status_code == 403:
            return cls.create(
                "PROVIDER_AUTH_FAILED",
                "AMap transit permission was denied",
                category=ProviderErrorCategory.PERMISSION_DENIED,
                retryable=False,
                started_at=started_at,
                safe_provider_code=safe_code,
            )
        if status_code == 429:
            return cls.create(
                "PROVIDER_RATE_LIMITED",
                "AMap transit rate limit was reached",
                retryable=True,
                started_at=started_at,
                safe_provider_code=safe_code,
                retry_after_seconds=retry_after_seconds,
            )
        if status_code >= 500:
            return cls.create(
                "PROVIDER_UNAVAILABLE",
                "AMap transit service is temporarily unavailable",
                retryable=True,
                started_at=started_at,
                safe_provider_code=safe_code,
            )
        return cls.create(
            "PROVIDER_ERROR",
            "AMap transit request failed",
            category=ProviderErrorCategory.INVALID_REQUEST,
            retryable=False,
            started_at=started_at,
            safe_provider_code=safe_code,
        )

    @classmethod
    def from_business(cls, infocode: str, started_at: float) -> ProviderFailure:
        if infocode in PERMISSION_CODES:
            return cls.create(
                "PROVIDER_AUTH_FAILED",
                "AMap transit permission was denied",
                category=ProviderErrorCategory.PERMISSION_DENIED,
                retryable=False,
                started_at=started_at,
                safe_provider_code=infocode,
            )
        if infocode in AUTH_CODES:
            return cls.create(
                "PROVIDER_AUTH_FAILED",
                "AMap transit authentication failed",
                retryable=False,
                started_at=started_at,
                safe_provider_code=infocode,
            )
        if infocode in RATE_CODES:
            return cls.create(
                "PROVIDER_RATE_LIMITED",
                "AMap transit rate limit was reached",
                retryable=True,
                started_at=started_at,
                safe_provider_code=infocode,
            )
        if infocode in QUOTA_CODES:
            return cls.create(
                "PROVIDER_QUOTA_EXHAUSTED",
                "AMap transit quota was exhausted",
                retryable=False,
                started_at=started_at,
                safe_provider_code=infocode,
            )
        if infocode in UNAVAILABLE_CODES or infocode.startswith("3"):
            return cls.create(
                "PROVIDER_UNAVAILABLE",
                "AMap transit service is temporarily unavailable",
                retryable=True,
                started_at=started_at,
                safe_provider_code=infocode,
            )
        if infocode in INVALID_REQUEST_CODES:
            return cls.create(
                "PROVIDER_REQUEST_INVALID",
                "AMap rejected the transit request parameters",
                retryable=False,
                started_at=started_at,
                safe_provider_code=infocode,
            )
        return cls.create(
            "PROVIDER_ERROR",
            "AMap transit service returned an error",
            retryable=False,
            started_at=started_at,
            category=ProviderErrorCategory.PROVIDER_ADAPTER_ERROR,
            safe_provider_code=infocode,
        )

    @staticmethod
    def create(
        error_code: ProviderErrorCode,
        error_message: str,
        *,
        category: ProviderErrorCategory | None = None,
        retryable: bool,
        started_at: float,
        safe_provider_code: str | None = None,
        cause_type: str | None = None,
        retry_after_seconds: float | None = None,
    ) -> ProviderFailure:
        return ProviderFailure(
            provider="AMAP",
            error_code=error_code,
            error_message=error_message,
            category=category or category_for_error_code(error_code),
            operation=ProviderOperation.ROUTE,
            retryable=retryable,
            safe_provider_code=safe_provider_code,
            cause_type=cause_type,
            retry_after_seconds=retry_after_seconds,
            latency_ms=AmapTransitFailures.elapsed_ms(started_at),
            fetched_at=datetime.now(UTC),
        )

    @staticmethod
    def elapsed_ms(started_at: float) -> int:
        return max(0, int((perf_counter() - started_at) * 1000))