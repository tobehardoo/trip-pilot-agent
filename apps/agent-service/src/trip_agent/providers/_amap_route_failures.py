"""Stable failure mapping for AMap route APIs."""

from datetime import UTC, datetime
from time import perf_counter

from trip_agent.providers.map import ProviderErrorCode, ProviderFailure


class AmapRouteFailures:
    _auth_codes = frozenset(
        {
            "10001",
            "10002",
            "10005",
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
    _rate_codes = frozenset(
        {"10004", "10014", "10015", "10016", "10019", "10020", "10021", "10029"}
    )
    _quota_codes = frozenset(
        {"10003", "10010", "10044", "10045", "40000", "40001", "40002", "40003"}
    )
    _unavailable_codes = frozenset({"10017"})
    _invalid_request_codes = frozenset({"20000", "20001", "20002", "20012"})

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
        if infocode in cls._auth_codes:
            return cls.create(
                "PROVIDER_AUTH_FAILED",
                "AMap route authentication failed",
                retryable=False,
                started_at=started_at,
            )
        if infocode in cls._rate_codes:
            return cls.create(
                "PROVIDER_RATE_LIMITED",
                "AMap route rate limit was reached",
                retryable=True,
                started_at=started_at,
            )
        if infocode in cls._quota_codes:
            return cls.create(
                "PROVIDER_QUOTA_EXHAUSTED",
                "AMap route quota was exhausted",
                retryable=False,
                started_at=started_at,
            )
        if infocode in cls._unavailable_codes or infocode.startswith("3"):
            return cls.create(
                "PROVIDER_UNAVAILABLE",
                "AMap route service is temporarily unavailable",
                retryable=True,
                started_at=started_at,
            )
        if infocode in cls._invalid_request_codes:
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
