import asyncio

import httpx
import pytest

from trip_agent.acquisition import HttpResourceFetcher
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


class _BytesStream(httpx.AsyncByteStream):
    def __init__(self, content: bytes) -> None:
        self._content = content

    async def __aiter__(self):
        yield self._content


class _ClosingTransport(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.closed = False

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if self.closed:
            raise RuntimeError("transport is closed")
        return httpx.Response(200, stream=_BytesStream(b"fresh"), request=request)

    async def aclose(self) -> None:
        self.closed = True


class _StaticHostResolver:
    def __init__(self, addresses_by_host: dict[str, tuple[str, ...]]) -> None:
        self._addresses_by_host = addresses_by_host
        self.calls: list[tuple[str, int]] = []

    async def resolve(self, hostname: str, port: int) -> tuple[str, ...]:
        self.calls.append((hostname, port))
        return self._addresses_by_host[hostname]


def test_fetch_pins_request_to_vetted_address_and_preserves_https_identity() -> None:
    source = _source()
    resource = DiscoveredResource(
        source_id=source.source_id,
        city=source.city,
        url=source.resource_urls[0],
    )
    resolver = _StaticHostResolver({"example.com": ("93.184.216.34",)})

    def handle(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://93.184.216.34/article"
        assert request.headers["Connection"] == "close"
        assert request.headers["Host"] == "example.com"
        assert request.extensions["sni_hostname"] == "example.com"
        return httpx.Response(200, stream=_BytesStream(b"vetted"), request=request)

    async def fetch() -> object:
        return await HttpResourceFetcher(
            http_transport_factory=lambda: httpx.MockTransport(handle),
            host_resolver=resolver,
        ).fetch(source=source, resource=resource)

    result = asyncio.run(fetch())

    assert result.status == "FETCHED"
    assert result.final_url == resource.url
    assert resolver.calls == [("example.com", 443)]


def test_fetch_uses_a_dedicated_transport_while_ignoring_environment_proxies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _source()
    resource = DiscoveredResource(
        source_id=source.source_id,
        city=source.city,
        url=source.resource_urls[0],
    )
    resolver = _StaticHostResolver({"example.com": ("93.184.216.34",)})
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")

    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=_BytesStream(b"direct"), request=request)

    result = asyncio.run(
        HttpResourceFetcher(
            http_transport_factory=lambda: httpx.MockTransport(handle),
            host_resolver=resolver,
        ).fetch(source=source, resource=resource)
    )

    assert result.status == "FETCHED"
    assert result.content == b"direct"


def test_reused_fetcher_creates_and_closes_a_fresh_transport_per_fetch() -> None:
    source = _source()
    resource = DiscoveredResource(
        source_id=source.source_id,
        city=source.city,
        url=source.resource_urls[0],
    )
    resolver = _StaticHostResolver({"example.com": ("93.184.216.34",)})
    created: list[_ClosingTransport] = []

    def create_transport() -> httpx.AsyncBaseTransport:
        transport = _ClosingTransport()
        created.append(transport)
        return transport

    fetcher = HttpResourceFetcher(
        http_transport_factory=create_transport,
        host_resolver=resolver,
    )

    async def fetch_twice() -> tuple[object, object]:
        first = await fetcher.fetch(source=source, resource=resource)
        second = await fetcher.fetch(source=source, resource=resource)
        return first, second

    first, second = asyncio.run(fetch_twice())

    assert first.status == "FETCHED"
    assert second.status == "FETCHED"
    assert len(created) == 2
    assert all(transport.closed for transport in created)


def test_fetch_pins_an_allowed_redirect_host_to_its_own_public_address() -> None:
    source = _source()
    resource = DiscoveredResource(
        source_id=source.source_id,
        city=source.city,
        url=source.resource_urls[0],
    )
    resolver = _StaticHostResolver(
        {
            "example.com": ("93.184.216.34",),
            "cdn.example.com": ("1.1.1.1",),
        }
    )

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.host == "93.184.216.34":
            assert request.headers["Host"] == "example.com"
            assert request.extensions["sni_hostname"] == "example.com"
            return httpx.Response(
                302,
                headers={"Location": "https://cdn.example.com/updated"},
                request=request,
            )
        assert str(request.url) == "https://1.1.1.1/updated"
        assert request.headers["Host"] == "cdn.example.com"
        assert request.extensions["sni_hostname"] == "cdn.example.com"
        return httpx.Response(200, stream=_BytesStream(b"updated"), request=request)

    async def fetch() -> object:
        return await HttpResourceFetcher(
            http_transport_factory=lambda: httpx.MockTransport(handle),
            host_resolver=resolver,
        ).fetch(source=source, resource=resource)

    result = asyncio.run(fetch())

    assert result.status == "FETCHED"
    assert result.final_url == "https://cdn.example.com/updated"
    assert result.content == b"updated"
    assert resolver.calls == [("example.com", 443), ("cdn.example.com", 443)]


def test_fetch_reuses_the_same_dns_pin_for_relative_redirects() -> None:
    source = _source()
    resource = DiscoveredResource(
        source_id=source.source_id,
        city=source.city,
        url=source.resource_urls[0],
    )
    resolver = _StaticHostResolver({"example.com": ("93.184.216.34",)})
    requested_urls: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        if request.url.path == "/article":
            return httpx.Response(
                302,
                headers={
                    "Location": "/updated",
                    "Set-Cookie": "session=untrusted; Path=/",
                },
                request=request,
            )
        assert "Cookie" not in request.headers
        return httpx.Response(200, stream=_BytesStream(b"updated"), request=request)

    async def fetch() -> object:
        return await HttpResourceFetcher(
            http_transport_factory=lambda: httpx.MockTransport(handle),
            host_resolver=resolver,
        ).fetch(source=source, resource=resource)

    result = asyncio.run(fetch())

    assert result.status == "FETCHED"
    assert result.final_url == "https://example.com/updated"
    assert resolver.calls == [("example.com", 443)]
    assert requested_urls == [
        "https://93.184.216.34/article",
        "https://93.184.216.34/updated",
    ]
