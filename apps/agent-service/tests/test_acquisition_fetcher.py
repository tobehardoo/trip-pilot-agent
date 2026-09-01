import asyncio
import gzip
from collections.abc import Callable
from datetime import UTC, datetime

import httpx
import pytest

from trip_agent.acquisition import (
    AcquisitionFetchError,
    FetchValidators,
    HttpResourceFetcher,
)
from trip_agent.acquisition.models import DiscoveredResource, KnowledgeSource


def _source() -> KnowledgeSource:
    return KnowledgeSource(
        source_id="official-source",
        city="广州",
        source_name="官方来源",
        reliability_level="OFFICIAL",
        allowed_domains=("example.com",),
        resource_urls=("https://example.com/article",),
        max_response_bytes=64 * 1024,
    )


class _ChunkedStream(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield b"a" * (32 * 1024)
        yield b"b" * (32 * 1024 + 1)


class _BytesStream(httpx.AsyncByteStream):
    def __init__(self, content: bytes) -> None:
        self._content = content

    async def __aiter__(self):
        yield self._content


class _StaticHostResolver:
    def __init__(self, addresses_by_host: dict[str, tuple[str, ...]]) -> None:
        self._addresses_by_host = addresses_by_host
        self.calls: list[tuple[str, int]] = []

    async def resolve(self, hostname: str, port: int) -> tuple[str, ...]:
        self.calls.append((hostname, port))
        return self._addresses_by_host[hostname]


def _fetcher(
    http_transport: httpx.AsyncBaseTransport,
    *,
    clock: Callable[[], datetime] | None = None,
) -> HttpResourceFetcher:
    return HttpResourceFetcher(
        http_transport_factory=lambda: http_transport,
        host_resolver=_StaticHostResolver({"example.com": ("93.184.216.34",)}),
        clock=clock,
    )


def test_conditional_fetch_returns_not_modified_without_reading_content() -> None:
    source = _source()
    resource = DiscoveredResource(
        source_id=source.source_id,
        city=source.city,
        url=source.resource_urls[0],
    )
    fetched_at = datetime(2026, 7, 20, 0, 0, tzinfo=UTC)

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.headers["If-None-Match"] == '"revision-1"'
        assert request.headers["If-Modified-Since"] == "Sun, 19 Jul 2026 00:00:00 GMT"
        return httpx.Response(
            304,
            headers={
                "ETag": '"revision-1"',
                "Last-Modified": "Sun, 19 Jul 2026 00:00:00 GMT",
            },
            request=request,
        )

    async def fetch() -> object:
        fetcher = _fetcher(httpx.MockTransport(handle), clock=lambda: fetched_at)
        return await fetcher.fetch(
            source=source,
            resource=resource,
            validators=FetchValidators(
                etag='"revision-1"',
                last_modified="Sun, 19 Jul 2026 00:00:00 GMT",
            ),
        )

    result = asyncio.run(fetch())

    assert result.status == "NOT_MODIFIED"
    assert result.requested_url == resource.url
    assert result.final_url == resource.url
    assert result.fetched_at == fetched_at
    assert result.validators.etag == '"revision-1"'
    assert result.validators.last_modified == "Sun, 19 Jul 2026 00:00:00 GMT"


def test_fetch_rejects_unconditional_not_modified_response() -> None:
    source = _source()
    resource = DiscoveredResource(
        source_id=source.source_id,
        city=source.city,
        url=source.resource_urls[0],
    )

    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(304, request=request)

    async def fetch() -> object:
        return await _fetcher(httpx.MockTransport(handle)).fetch(
                source=source,
                resource=resource,
            )

    with pytest.raises(AcquisitionFetchError) as raised:
        asyncio.run(fetch())

    assert raised.value.code == "UNEXPECTED_NOT_MODIFIED"
    assert raised.value.retryable is False
    assert raised.value.status_code == 304


def test_successful_fetch_returns_bounded_content_and_response_metadata() -> None:
    source = _source()
    resource = DiscoveredResource(
        source_id=source.source_id,
        city=source.city,
        url=source.resource_urls[0],
    )
    fetched_at = datetime(2026, 7, 20, 1, 0, tzinfo=UTC)
    body = "<html><main>广州官方资料</main></html>".encode()

    def handle(request: httpx.Request) -> httpx.Response:
        assert "If-None-Match" not in request.headers
        assert "If-Modified-Since" not in request.headers
        assert request.headers["Accept-Encoding"] == "identity"
        return httpx.Response(
            200,
            headers={
                "Content-Type": "text/html; charset=utf-8",
                "ETag": '"revision-2"',
                "Last-Modified": "Mon, 20 Jul 2026 00:30:00 GMT",
            },
            stream=_BytesStream(body),
            request=request,
        )

    async def fetch() -> object:
        fetcher = _fetcher(httpx.MockTransport(handle), clock=lambda: fetched_at)
        return await fetcher.fetch(source=source, resource=resource)

    result = asyncio.run(fetch())

    assert result.status == "FETCHED"
    assert result.requested_url == resource.url
    assert result.final_url == resource.url
    assert result.fetched_at == fetched_at
    assert result.content == body
    assert result.content_type == "text/html; charset=utf-8"
    assert result.validators.etag == '"revision-2"'
    assert result.validators.last_modified == "Mon, 20 Jul 2026 00:30:00 GMT"


def test_modified_response_clears_previous_validators_when_server_omits_them() -> None:
    source = _source()
    resource = DiscoveredResource(
        source_id=source.source_id,
        city=source.city,
        url=source.resource_urls[0],
    )

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.headers["If-None-Match"] == '"stale"'
        return httpx.Response(200, stream=_BytesStream(b"changed"), request=request)

    async def fetch() -> object:
        return await _fetcher(httpx.MockTransport(handle)).fetch(
                source=source,
                resource=resource,
                validators=FetchValidators(etag='"stale"'),
            )

    result = asyncio.run(fetch())

    assert result.status == "FETCHED"
    assert result.validators.etag is None
    assert result.validators.last_modified is None


def test_fetch_rejects_declared_oversized_response_before_reading_content() -> None:
    source = _source()
    resource = DiscoveredResource(
        source_id=source.source_id,
        city=source.city,
        url=source.resource_urls[0],
    )

    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Length": str(source.max_response_bytes + 1)},
            request=request,
        )

    async def fetch() -> object:
        return await _fetcher(httpx.MockTransport(handle)).fetch(
                source=source,
                resource=resource,
            )

    with pytest.raises(AcquisitionFetchError) as raised:
        asyncio.run(fetch())

    assert raised.value.code == "RESPONSE_TOO_LARGE"
    assert raised.value.retryable is False


def test_fetch_rejects_streamed_response_when_accumulated_bytes_exceed_limit() -> None:
    source = _source()
    resource = DiscoveredResource(
        source_id=source.source_id,
        city=source.city,
        url=source.resource_urls[0],
    )

    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=_ChunkedStream(), request=request)

    async def fetch() -> object:
        return await _fetcher(httpx.MockTransport(handle)).fetch(
                source=source,
                resource=resource,
            )

    with pytest.raises(AcquisitionFetchError) as raised:
        asyncio.run(fetch())

    assert raised.value.code == "RESPONSE_TOO_LARGE"
    assert raised.value.retryable is False


def test_fetch_rejects_encoded_response_before_decoding_content() -> None:
    source = _source()
    resource = DiscoveredResource(
        source_id=source.source_id,
        city=source.city,
        url=source.resource_urls[0],
    )
    compressed = gzip.compress(b"a" * (source.max_response_bytes + 1))

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.headers["Accept-Encoding"] == "identity"
        return httpx.Response(
            200,
            headers={"Content-Encoding": "gzip"},
            stream=_BytesStream(compressed),
            request=request,
        )

    async def fetch() -> object:
        return await _fetcher(httpx.MockTransport(handle)).fetch(
                source=source,
                resource=resource,
            )

    with pytest.raises(AcquisitionFetchError) as raised:
        asyncio.run(fetch())

    assert raised.value.code == "UNSUPPORTED_CONTENT_ENCODING"
    assert raised.value.retryable is False


def test_fetch_rejects_redirect_outside_source_allowlist_before_following() -> None:
    source = _source()
    resource = DiscoveredResource(
        source_id=source.source_id,
        city=source.city,
        url=source.resource_urls[0],
    )
    requested_urls: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        return httpx.Response(
            302,
            headers={"Location": "https://outside.example.net/article"},
            request=request,
        )

    async def fetch() -> object:
        return await _fetcher(httpx.MockTransport(handle)).fetch(
                source=source,
                resource=resource,
            )

    with pytest.raises(AcquisitionFetchError) as raised:
        asyncio.run(fetch())

    assert raised.value.code == "UNSAFE_REDIRECT"
    assert raised.value.retryable is False
    assert requested_urls == ["https://93.184.216.34/article"]


def test_fetch_classifies_malformed_redirect_as_unsafe_before_following() -> None:
    source = _source()
    resource = DiscoveredResource(
        source_id=source.source_id,
        city=source.city,
        url=source.resource_urls[0],
    )
    requested_urls: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        return httpx.Response(
            302,
            headers={"Location": "https://[:::]/article"},
            request=request,
        )

    async def fetch() -> object:
        return await _fetcher(httpx.MockTransport(handle)).fetch(
                source=source,
                resource=resource,
            )

    with pytest.raises(AcquisitionFetchError) as raised:
        asyncio.run(fetch())

    assert raised.value.code == "UNSAFE_REDIRECT"
    assert raised.value.retryable is False
    assert requested_urls == ["https://93.184.216.34/article"]


def test_fetch_follows_validated_relative_redirect_and_records_final_url() -> None:
    source = _source()
    resource = DiscoveredResource(
        source_id=source.source_id,
        city=source.city,
        url=source.resource_urls[0],
    )
    requested_urls: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        if request.url.path == "/article":
            return httpx.Response(302, headers={"Location": "/updated"}, request=request)
        return httpx.Response(
            200,
            headers={"Content-Type": "text/html"},
            stream=_BytesStream(b"<html>updated</html>"),
            request=request,
        )

    async def fetch() -> object:
        return await _fetcher(httpx.MockTransport(handle)).fetch(
                source=source,
                resource=resource,
            )

    result = asyncio.run(fetch())

    assert result.status == "FETCHED"
    assert result.requested_url == resource.url
    assert result.final_url == "https://example.com/updated"
    assert result.content == b"<html>updated</html>"
    assert requested_urls == [
        "https://93.184.216.34/article",
        "https://93.184.216.34/updated",
    ]


def test_fetch_maps_http_timeout_to_retryable_acquisition_error() -> None:
    source = _source()
    resource = DiscoveredResource(
        source_id=source.source_id,
        city=source.city,
        url=source.resource_urls[0],
    )

    def handle(request: httpx.Request) -> httpx.Response:
        timeout = request.extensions["timeout"]
        assert timeout["connect"] == source.request_timeout_seconds
        assert timeout["read"] == source.request_timeout_seconds
        raise httpx.ReadTimeout("timed out", request=request)

    async def fetch() -> object:
        return await _fetcher(httpx.MockTransport(handle)).fetch(
                source=source,
                resource=resource,
            )

    with pytest.raises(AcquisitionFetchError) as raised:
        asyncio.run(fetch())

    assert raised.value.code == "REQUEST_TIMEOUT"
    assert raised.value.retryable is True


@pytest.mark.parametrize(
    ("status_code", "retryable"),
    [(404, False), (429, True), (503, True)],
)
def test_fetch_classifies_unsuccessful_http_statuses(
    status_code: int,
    retryable: bool,
) -> None:
    source = _source()
    resource = DiscoveredResource(
        source_id=source.source_id,
        city=source.city,
        url=source.resource_urls[0],
    )

    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, request=request)

    async def fetch() -> object:
        return await _fetcher(httpx.MockTransport(handle)).fetch(
                source=source,
                resource=resource,
            )

    with pytest.raises(AcquisitionFetchError) as raised:
        asyncio.run(fetch())

    assert raised.value.code == "HTTP_STATUS_ERROR"
    assert raised.value.retryable is retryable
    assert raised.value.status_code == status_code


def test_fetch_maps_transport_failure_to_retryable_acquisition_error() -> None:
    source = _source()
    resource = DiscoveredResource(
        source_id=source.source_id,
        city=source.city,
        url=source.resource_urls[0],
    )

    def handle(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection failed", request=request)

    async def fetch() -> object:
        return await _fetcher(httpx.MockTransport(handle)).fetch(
                source=source,
                resource=resource,
            )

    with pytest.raises(AcquisitionFetchError) as raised:
        asyncio.run(fetch())

    assert raised.value.code == "REQUEST_FAILED"
    assert raised.value.retryable is True
    assert raised.value.status_code is None
