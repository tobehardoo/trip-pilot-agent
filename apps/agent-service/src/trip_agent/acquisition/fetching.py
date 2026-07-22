"""Bounded HTTP acquisition with DNS-pinned conditional requests."""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from urllib.parse import urljoin

import httpx

from trip_agent.acquisition.dns import (
    HostResolutionError,
    HostResolver,
    PinnedRequestTarget,
    PublicHostResolution,
    SystemHostResolver,
    UnsafeHostResolutionError,
    resolve_request_target,
)
from trip_agent.acquisition.fetch_models import (
    AcquisitionFetchError,
    FetchResult,
    FetchValidators,
    ResourceFetched,
    ResourceNotModified,
)
from trip_agent.acquisition.models import DiscoveredResource, KnowledgeSource
from trip_agent.acquisition.security import SourceSecurityError, validate_source_url

_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


class HttpResourceFetcher:
    """Fetch approved resources without letting HTTPX follow redirects implicitly."""

    def __init__(
        self,
        *,
        http_transport_factory: Callable[[], httpx.AsyncBaseTransport] | None = None,
        host_resolver: HostResolver | None = None,
        clock: Callable[[], datetime] | None = None,
        max_redirects: int = 3,
    ) -> None:
        if max_redirects < 0:
            raise ValueError("max_redirects cannot be negative")
        self._http_transport_factory = http_transport_factory
        self._host_resolver = host_resolver or SystemHostResolver()
        self._clock = clock or _utc_now
        self._max_redirects = max_redirects

    async def fetch(
        self,
        *,
        source: KnowledgeSource,
        resource: DiscoveredResource,
        validators: FetchValidators | None = None,
    ) -> FetchResult:
        transport = (
            self._http_transport_factory() if self._http_transport_factory is not None else None
        )
        async with httpx.AsyncClient(
            transport=transport,
            trust_env=False,
            http1=True,
            http2=False,
        ) as http_client:
            return await self._fetch_with_client(
                http_client=http_client,
                source=source,
                resource=resource,
                validators=validators,
            )

    async def _fetch_with_client(
        self,
        *,
        http_client: httpx.AsyncClient,
        source: KnowledgeSource,
        resource: DiscoveredResource,
        validators: FetchValidators | None,
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
        pinned_hosts: dict[str, PublicHostResolution] = {}
        for redirect_count in range(self._max_redirects + 1):
            try:
                target = await resolve_request_target(
                    logical_url=current_url,
                    resolver=self._host_resolver,
                    pinned_hosts=pinned_hosts,
                    timeout=source.request_timeout_seconds,
                )
            except UnsafeHostResolutionError as error:
                raise AcquisitionFetchError(
                    "UNSAFE_RESOLVED_ADDRESS",
                    f"resource host failed DNS safety policy: {error}",
                    retryable=False,
                ) from error
            except (TimeoutError, OSError, HostResolutionError) as error:
                raise AcquisitionFetchError(
                    "DNS_RESOLUTION_FAILED",
                    f"resource host could not be resolved: {httpx.URL(current_url).host}",
                    retryable=True,
                ) from error
            async with _request_stream(
                http_client=http_client,
                target=target,
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
                        final_url=current_url,
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
                        current_url,
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
                    final_url=current_url,
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
    target: PinnedRequestTarget,
    headers: dict[str, str],
    timeout: float,
) -> AsyncIterator[httpx.Response]:
    # IP-based origins must not share a pooled TLS connection across logical hosts.
    http_client.cookies.clear()
    request_headers = {
        **headers,
        "Connection": "close",
        "Host": target.hostname,
    }
    try:
        async with http_client.stream(
            "GET",
            target.network_url,
            headers=request_headers,
            timeout=timeout,
            follow_redirects=False,
            extensions={"sni_hostname": target.hostname},
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
