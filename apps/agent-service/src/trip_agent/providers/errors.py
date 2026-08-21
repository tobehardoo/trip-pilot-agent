"""Stable provider failure taxonomy and fallback decisions."""

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Protocol


class ProviderExecutionMode(StrEnum):
    DEMO_ONLY = "DEMO_ONLY"
    REAL_ONLY = "REAL_ONLY"
    REAL_WITH_EXPLICIT_FALLBACK = "REAL_WITH_EXPLICIT_FALLBACK"


class ProviderErrorCategory(StrEnum):
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
    AUTHENTICATION_ERROR = "AUTHENTICATION_ERROR"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    QUOTA_EXCEEDED = "QUOTA_EXCEEDED"
    RATE_LIMITED = "RATE_LIMITED"
    TIMEOUT = "TIMEOUT"
    NETWORK_ERROR = "NETWORK_ERROR"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    INVALID_REQUEST = "INVALID_REQUEST"
    NO_RESULT = "NO_RESULT"
    UNSUPPORTED_MODE = "UNSUPPORTED_MODE"
    MALFORMED_RESPONSE = "MALFORMED_RESPONSE"
    DATA_QUALITY_ERROR = "DATA_QUALITY_ERROR"
    PROVIDER_ADAPTER_ERROR = "PROVIDER_ADAPTER_ERROR"
    PLANNING_INFEASIBLE = "PLANNING_INFEASIBLE"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ProviderOperation(StrEnum):
    CONFIGURATION = "CONFIGURATION"
    PLANNING = "PLANNING"
    REPLANNING = "REPLANNING"
    POI_SEARCH = "POI_SEARCH"
    ROUTE = "ROUTE"


class FallbackDecision(StrEnum):
    ALLOW_FALLBACK = "ALLOW_FALLBACK"
    DENY_FALLBACK = "DENY_FALLBACK"
    LOCAL_FAILURE = "LOCAL_FAILURE"
    GLOBAL_FAILURE = "GLOBAL_FAILURE"


@dataclass(frozen=True, slots=True)
class ProviderFailureDetails:
    category: ProviderErrorCategory
    error_code: str
    provider: str
    operation: ProviderOperation
    retryable: bool
    fallback_allowed: bool
    safe_provider_code: str | None
    safe_message: str
    retry_count: int
    cause_type: str | None
    retry_exhausted: bool = False
    fallback_attempted: bool = False
    fallback_succeeded: bool = False


class _ProviderFailureLike(Protocol):
    error_code: str
    error_message: str
    provider: str
    category: ProviderErrorCategory
    retryable: bool
    fallback_allowed: bool
    safe_provider_code: str | None
    retry_count: int
    cause_type: str | None
    retry_exhausted: bool


class PlanningProviderError(Exception):
    """One safe, structured provider failure used across the planning pipeline."""

    def __init__(self, details: ProviderFailureDetails | str) -> None:
        if isinstance(details, str):
            category = category_for_error_code(details)
            retryable = category in ProviderFallbackPolicy._explicitly_allowed
            details = ProviderFailureDetails(
                category=category,
                error_code=details,
                provider="PLANNER",
                operation=ProviderOperation.PLANNING,
                retryable=retryable,
                fallback_allowed=False,
                safe_provider_code=None,
                safe_message=safe_message_for_error_code(details),
                retry_count=2 if retryable else 0,
                cause_type=None,
                retry_exhausted=retryable,
            )
        super().__init__(details.safe_message)
        self.details = details

    @classmethod
    def from_failure(
        cls,
        failure: _ProviderFailureLike,
        *,
        operation: ProviderOperation | None = None,
    ) -> "PlanningProviderError":
        return cls(
            ProviderFailureDetails(
                category=failure.category,
                error_code=failure.error_code,
                provider=failure.provider,
                operation=operation or ProviderOperation(failure.operation),
                retryable=failure.retryable,
                fallback_allowed=failure.fallback_allowed,
                safe_provider_code=failure.safe_provider_code,
                safe_message=failure.error_message,
                retry_count=failure.retry_count,
                cause_type=failure.cause_type,
                retry_exhausted=failure.retry_exhausted,
            )
        )

    def with_fallback(
        self,
        *,
        allowed: bool,
        attempted: bool,
        succeeded: bool,
    ) -> "PlanningProviderError":
        return PlanningProviderError(
            replace(
                self.details,
                fallback_allowed=allowed,
                fallback_attempted=attempted,
                fallback_succeeded=succeeded,
            )
        )


class ProviderFallbackPolicy:
    """The only policy allowed to authorize a real-to-Demo fallback."""

    _explicitly_allowed = frozenset(
        {
            ProviderErrorCategory.TIMEOUT,
            ProviderErrorCategory.NETWORK_ERROR,
            ProviderErrorCategory.PROVIDER_UNAVAILABLE,
            ProviderErrorCategory.RATE_LIMITED,
        }
    )
    _local = frozenset(
        {
            ProviderErrorCategory.NO_RESULT,
            ProviderErrorCategory.UNSUPPORTED_MODE,
        }
    )
    _configurable = frozenset(
        {
            ProviderErrorCategory.QUOTA_EXCEEDED,
            ProviderErrorCategory.MALFORMED_RESPONSE,
        }
    )

    def __init__(
        self,
        *,
        additional_allowed_categories: frozenset[ProviderErrorCategory] = frozenset(),
    ) -> None:
        unsupported = additional_allowed_categories - self._configurable
        if unsupported:
            categories = ", ".join(sorted(item.value for item in unsupported))
            raise ValueError(f"{categories} cannot be enabled for fallback")
        self._additional_allowed_categories = additional_allowed_categories

    def decide(
        self,
        mode: ProviderExecutionMode,
        failure: ProviderFailureDetails,
    ) -> FallbackDecision:
        if failure.category in self._local:
            return FallbackDecision.LOCAL_FAILURE
        if mode != ProviderExecutionMode.REAL_WITH_EXPLICIT_FALLBACK:
            return FallbackDecision.DENY_FALLBACK
        if (
            failure.category in self._explicitly_allowed
            and failure.retryable
            and failure.retry_exhausted
        ):
            return FallbackDecision.ALLOW_FALLBACK
        if failure.category not in self._additional_allowed_categories:
            return FallbackDecision.DENY_FALLBACK
        if failure.category == ProviderErrorCategory.QUOTA_EXCEEDED:
            return FallbackDecision.ALLOW_FALLBACK
        if failure.category == ProviderErrorCategory.MALFORMED_RESPONSE:
            return (
                FallbackDecision.ALLOW_FALLBACK
                if failure.retryable and failure.retry_exhausted
                else FallbackDecision.DENY_FALLBACK
            )
        return FallbackDecision.DENY_FALLBACK


def category_for_error_code(error_code: str) -> ProviderErrorCategory:
    return {
        "POI_NOT_FOUND": ProviderErrorCategory.NO_RESULT,
        "ROUTE_NOT_FOUND": ProviderErrorCategory.NO_RESULT,
        "PROVIDER_AUTH_FAILED": ProviderErrorCategory.AUTHENTICATION_ERROR,
        "PROVIDER_PERMISSION_DENIED": ProviderErrorCategory.PERMISSION_DENIED,
        "PROVIDER_RATE_LIMITED": ProviderErrorCategory.RATE_LIMITED,
        "PROVIDER_QUOTA_EXHAUSTED": ProviderErrorCategory.QUOTA_EXCEEDED,
        "PROVIDER_REQUEST_INVALID": ProviderErrorCategory.INVALID_REQUEST,
        "PROVIDER_TIMEOUT": ProviderErrorCategory.TIMEOUT,
        "PROVIDER_NETWORK_ERROR": ProviderErrorCategory.NETWORK_ERROR,
        "PROVIDER_UNAVAILABLE": ProviderErrorCategory.PROVIDER_UNAVAILABLE,
        "PROVIDER_UNSUPPORTED_MODE": ProviderErrorCategory.UNSUPPORTED_MODE,
        "PROVIDER_SCHEMA_CHANGED": ProviderErrorCategory.MALFORMED_RESPONSE,
        "INSUFFICIENT_AMAP_POIS": ProviderErrorCategory.NO_RESULT,
    }.get(error_code, ProviderErrorCategory.INTERNAL_ERROR)


def safe_message_for_error_code(error_code: str) -> str:
    return {
        "POI_NOT_FOUND": "No matching POIs were found",
        "ROUTE_NOT_FOUND": "No route was found",
        "PROVIDER_AUTH_FAILED": "Provider authentication failed",
        "PROVIDER_PERMISSION_DENIED": "Provider permission was denied",
        "PROVIDER_RATE_LIMITED": "Provider rate limit was reached",
        "PROVIDER_QUOTA_EXHAUSTED": "Provider quota was exhausted",
        "PROVIDER_REQUEST_INVALID": "Provider rejected the request",
        "PROVIDER_TIMEOUT": "Provider request timed out",
        "PROVIDER_NETWORK_ERROR": "Provider network request failed",
        "PROVIDER_UNAVAILABLE": "Provider is temporarily unavailable",
        "PROVIDER_UNSUPPORTED_MODE": "The requested route mode is not supported",
        "PROVIDER_SCHEMA_CHANGED": "Provider returned a malformed response",
        "INSUFFICIENT_AMAP_POIS": "Not enough real POIs were found",
    }.get(error_code, error_code)
