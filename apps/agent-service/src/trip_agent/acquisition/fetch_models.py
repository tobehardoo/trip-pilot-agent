"""Typed results and errors emitted by knowledge resource fetching."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

type FetchErrorCode = Literal[
    "DNS_RESOLUTION_FAILED",
    "HTTP_STATUS_ERROR",
    "RESPONSE_TOO_LARGE",
    "REQUEST_TIMEOUT",
    "REQUEST_FAILED",
    "TOO_MANY_REDIRECTS",
    "UNEXPECTED_NOT_MODIFIED",
    "UNSUPPORTED_CONTENT_ENCODING",
    "UNSAFE_REDIRECT",
    "UNSAFE_RESOLVED_ADDRESS",
]


class AcquisitionFetchError(RuntimeError):
    def __init__(
        self,
        code: FetchErrorCode,
        message: str,
        *,
        retryable: bool,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class FetchValidators:
    etag: str | None = None
    last_modified: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "etag", _normalize_header_value(self.etag, "etag"))
        object.__setattr__(
            self,
            "last_modified",
            _normalize_header_value(self.last_modified, "last_modified"),
        )


@dataclass(frozen=True, slots=True)
class ResourceNotModified:
    status: Literal["NOT_MODIFIED"]
    requested_url: str
    final_url: str
    fetched_at: datetime
    validators: FetchValidators


@dataclass(frozen=True, slots=True)
class ResourceFetched:
    status: Literal["FETCHED"]
    requested_url: str
    final_url: str
    fetched_at: datetime
    content: bytes
    content_type: str | None
    validators: FetchValidators


type FetchResult = ResourceFetched | ResourceNotModified


def _normalize_header_value(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string or None")
    normalized = value.strip()
    if not normalized or "\r" in normalized or "\n" in normalized:
        raise ValueError(f"{field_name} must be a safe non-empty HTTP header value")
    return normalized
