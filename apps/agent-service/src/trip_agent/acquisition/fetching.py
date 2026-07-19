"""Bounded HTTP acquisition with explicit conditional-request outcomes."""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from urllib.parse import urljoin

import httpx

from trip_agent.acquisition.models import DiscoveredResource, KnowledgeSource
from trip_agent.acquisition.security import SourceSecurityError, validate_source_url

type FetchErrorCode = Literal[
    "HTTP_STATUS_ERROR",
    "RESPONSE_TOO_LARGE",
    "REQUEST_TIMEOUT",
    "REQUEST_FAILED",
    "TOO_MANY_REDIRECTS",
    "UNEXPECTED_NOT_MODIFIED",
    "UNSUPPORTED_CONTENT_ENCODING",
    "UNSAFE_REDIRECT",
]

_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


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


class HttpResourceFetcher:
    """Fetch approved resources without letting HTTPX follow redirects implicitly."""

    def __init__(
        self,
        *,
        http_client: httpx.AsyncClient,
        clock: Callable[[], datetime] | None = None,
        max_redirects: int = 3,
    ) -> None:
        if max_redirects < 0:
            raise ValueError("max_redirects cannot be negative")
        self._http_client = http_client
        self._clock = clock or _utc_now
        self._max_redirects = max_redirects

    async def fetch(
        self,
        *,
        source: KnowledgeSource,
        resource: DiscoveredResource,
        validators: FetchValidators | None = None,
    ) -> FetchResult:
        _validate_resource_owner(source, resource)
        url = validate_source_url(resource.url, allowed_domains=source.allowed_domains)
        previous = validators or FetchValidators()
        headers = {
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Encoding": "identity",
            "User-Agent": "TripPilotKnowledgeAcquisition/0.1",
        }
        if previous.etag is not None:
            headers["If-None-Match"] = previous.etag
        if previous.last_modified is not None:
            headers["If-Modified-Since"] = previous.last_modified

        current_url = url
        for redirect_count in range(self._max_redirects + 1):
            async with _request_stream(
                http_client=self._http_client,
                url=current_url,
                headers=headers,
                timeout=source.request_timeout_seconds,
            ) as response:
                if response.status_code == 304:
                    if previous.etag is None and previous.last_modified is None:
                        raise AcquisitionFetchError(
                            "UNEXPECTED_NOT_MODIFIED",
                            "resource returned HTTP 304 without a conditional request",
                            retryable=False,
                            status_code=304,
                        )
                    return ResourceNotModified(
                        status="NOT_MODIFIED",
                        requested_url=resource.url,
                        final_url=str(response.url),
                        fetched_at=_require_aware_datetime(self._clock()),
                        validators=FetchValidators(
                            etag=response.headers.get("ETag") or previous.etag,
                            last_modified=(
                                response.headers.get("Last-Modified")
                                or previous.last_modified
                            ),
                        ),
                    )
                if response.status_code in _REDIRECT_STATUSES:
                    if redirect_count == self._max_redirects:
                        raise AcquisitionFetchError(
                            "TOO_MANY_REDIRECTS",
                            f"resource exceeded {self._max_redirects} redirects",
                            retryable=False,
                        )
                    redirect_url = urljoin(
                        str(response.url),
                        response.headers.get("Location", ""),
                    )
                    try:
                        current_url = validate_source_url(
                            redirect_url,
                            allowed_domains=source.allowed_domains,
                        )
                    except SourceSecurityError as error:
                        raise AcquisitionFetchError(
                            "UNSAFE_REDIRECT",
                            f"redirect violates source URL policy: {error}",
                            retryable=False,
                        ) from error
                    continue
                if not 200 <= response.status_code < 300:
                    raise AcquisitionFetchError(
                        "HTTP_STATUS_ERROR",
                        f"resource request returned HTTP {response.status_code}",
                        retryable=(response.status_code == 429 or response.status_code >= 500),
                        status_code=response.status_code,
                    )
                return ResourceFetched(
                    status="FETCHED",
                    requested_url=resource.url,
                    final_url=str(response.url),
                    fetched_at=_require_aware_datetime(self._clock()),
                    content=await _read_bounded_content(response, source.max_response_bytes),
                    content_type=response.headers.get("Content-Type"),
                    validators=FetchValidators(
                        etag=response.headers.get("ETag"),
                        last_modified=response.headers.get("Last-Modified"),
                    ),
                )
        raise AssertionError("redirect loop exhausted without returning")


@asynccontextmanager
async def _request_stream(
    *,
    http_client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    timeout: float,
) -> AsyncIterator[httpx.Response]:
    try:
        async with http_client.stream(
            "GET",
            url,
            headers=headers,
            timeout=timeout,
            follow_redirects=False,
        ) as response:
            yield response
    except httpx.InvalidURL as error:
        raise AcquisitionFetchError(
            "UNSAFE_REDIRECT",
            "redirect contains an invalid URL",
            retryable=False,
        ) from error
    except httpx.RemoteProtocolError as error:
        if str(error).startswith("Invalid URL in location header:"):
            raise AcquisitionFetchError(
                "UNSAFE_REDIRECT",
                "redirect contains an invalid URL",
                retryable=False,
            ) from error
        raise AcquisitionFetchError(
            "REQUEST_FAILED",
            "resource request failed",
            retryable=True,
        ) from error
    except httpx.TimeoutException as error:
        raise AcquisitionFetchError(
            "REQUEST_TIMEOUT",
            "resource request timed out",
            retryable=True,
        ) from error
    except httpx.RequestError as error:
        raise AcquisitionFetchError(
            "REQUEST_FAILED",
            "resource request failed",
            retryable=True,
        ) from error


def _validate_resource_owner(source: KnowledgeSource, resource: DiscoveredResource) -> None:
    if resource.source_id != source.source_id or resource.city != source.city:
        raise ValueError("discovered resource does not belong to the source")


def _normalize_header_value(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string or None")
    normalized = value.strip()
    if not normalized or "\r" in normalized or "\n" in normalized:
        raise ValueError(f"{field_name} must be a safe non-empty HTTP header value")
    return normalized


def _require_aware_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("fetch clock must return a timezone-aware datetime")
    return value


async def _read_bounded_content(response: httpx.Response, limit: int) -> bytes:
    content_encoding = response.headers.get("Content-Encoding", "identity").strip().casefold()
    if content_encoding not in {"", "identity"}:
        raise AcquisitionFetchError(
            "UNSUPPORTED_CONTENT_ENCODING",
            f"resource returned unsupported content encoding: {content_encoding}",
            retryable=False,
        )
    declared_size = response.headers.get("Content-Length")
    if declared_size is not None:
        try:
            exceeds_limit = int(declared_size) > limit
        except ValueError:
            exceeds_limit = False
        if exceeds_limit:
            raise AcquisitionFetchError(
                "RESPONSE_TOO_LARGE",
                f"resource response exceeds {limit} bytes",
                retryable=False,
            )
    chunks: list[bytes] = []
    size = 0
    async for chunk in response.aiter_raw():
        size += len(chunk)
        if size > limit:
            raise AcquisitionFetchError(
                "RESPONSE_TOO_LARGE",
                f"resource response exceeds {limit} bytes",
                retryable=False,
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _utc_now() -> datetime:
    return datetime.now(UTC)
