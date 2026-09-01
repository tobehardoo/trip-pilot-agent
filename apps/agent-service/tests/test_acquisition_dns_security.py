import asyncio

import httpx
import pytest

from trip_agent.acquisition import AcquisitionFetchError, HttpResourceFetcher
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


class _StaticHostResolver:
    def __init__(self, addresses_by_host: dict[str, tuple[str, ...]]) -> None:
        self._addresses_by_host = addresses_by_host
        self.calls: list[tuple[str, int]] = []

    async def resolve(self, hostname: str, port: int) -> tuple[str, ...]:
        self.calls.append((hostname, port))
        return self._addresses_by_host[hostname]


class _FailingHostResolver:
    async def resolve(self, hostname: str, port: int) -> tuple[str, ...]:
        raise OSError(f"cannot resolve {hostname}:{port}")


@pytest.mark.parametrize(
    "addresses",
    [
        ("127.0.0.1",),
        ("93.184.216.34", "10.0.0.8"),
        ("224.0.0.1",),
        ("2001:db8::1",),
        ("ff02::1",),
    ],
)
def test_fetch_rejects_any_non_public_dns_result_before_request(
    addresses: tuple[str, ...],
) -> None:
    source = _source()
    resource = DiscoveredResource(
        source_id=source.source_id,
        city=source.city,
        url=source.resource_urls[0],
    )
    resolver = _StaticHostResolver({"example.com": addresses})
    request_count = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return httpx.Response(200, request=request)

    async def fetch() -> object:
        return await HttpResourceFetcher(
            http_transport_factory=lambda: httpx.MockTransport(handle),
            host_resolver=resolver,
        ).fetch(source=source, resource=resource)

    with pytest.raises(AcquisitionFetchError) as raised:
        asyncio.run(fetch())

    assert raised.value.code == "UNSAFE_RESOLVED_ADDRESS"
    assert raised.value.retryable is False
    assert request_count == 0


def test_fetch_resolves_and_checks_a_new_redirect_host_before_following() -> None:
    source = _source()
    resource = DiscoveredResource(
        source_id=source.source_id,
        city=source.city,
        url=source.resource_urls[0],
    )
    resolver = _StaticHostResolver(
        {
            "example.com": ("93.184.216.34",),
            "cdn.example.com": ("192.168.10.20",),
        }
    )
    requested_urls: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        return httpx.Response(
            302,
            headers={"Location": "https://cdn.example.com/updated"},
            request=request,
        )

    async def fetch() -> object:
        return await HttpResourceFetcher(
            http_transport_factory=lambda: httpx.MockTransport(handle),
            host_resolver=resolver,
        ).fetch(source=source, resource=resource)

    with pytest.raises(AcquisitionFetchError) as raised:
        asyncio.run(fetch())

    assert raised.value.code == "UNSAFE_RESOLVED_ADDRESS"
    assert resolver.calls == [("example.com", 443), ("cdn.example.com", 443)]
    assert requested_urls == ["https://93.184.216.34/article"]


def test_fetch_maps_dns_failure_before_request_to_retryable_error() -> None:
    source = _source()
    resource = DiscoveredResource(
        source_id=source.source_id,
        city=source.city,
        url=source.resource_urls[0],
    )
    request_count = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return httpx.Response(200, request=request)

    async def fetch() -> object:
        return await HttpResourceFetcher(
            http_transport_factory=lambda: httpx.MockTransport(handle),
            host_resolver=_FailingHostResolver(),
        ).fetch(source=source, resource=resource)

    with pytest.raises(AcquisitionFetchError) as raised:
        asyncio.run(fetch())

    assert raised.value.code == "DNS_RESOLUTION_FAILED"
    assert raised.value.retryable is True
    assert request_count == 0


@pytest.mark.parametrize("addresses", [(), ("not-an-ip",)])
def test_fetch_maps_unusable_dns_results_to_retryable_error(
    addresses: tuple[str, ...],
) -> None:
    source = _source()
    resource = DiscoveredResource(
        source_id=source.source_id,
        city=source.city,
        url=source.resource_urls[0],
    )
    resolver = _StaticHostResolver({"example.com": addresses})

    def reject_request(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected request: {request.url}")

    async def fetch() -> object:
        return await HttpResourceFetcher(
            http_transport_factory=lambda: httpx.MockTransport(reject_request),
            host_resolver=resolver,
        ).fetch(source=source, resource=resource)

    with pytest.raises(AcquisitionFetchError) as raised:
        asyncio.run(fetch())

    assert raised.value.code == "DNS_RESOLUTION_FAILED"
    assert raised.value.retryable is True


def test_fetch_uses_system_resolver_for_public_ip_literal() -> None:
    source = KnowledgeSource(
        source_id="literal-ip-source",
        city="广州",
        source_name="公网地址来源",
        reliability_level="OFFICIAL",
        allowed_domains=("93.184.216.34",),
        resource_urls=("https://93.184.216.34/article",),
        max_response_bytes=64 * 1024,
    )
    resource = DiscoveredResource(
        source_id=source.source_id,
        city=source.city,
        url=source.resource_urls[0],
    )

    def handle(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == resource.url
        assert request.headers["Host"] == "93.184.216.34"
        assert request.extensions["sni_hostname"] == "93.184.216.34"
        return httpx.Response(200, stream=_BytesStream(b"literal"), request=request)

    async def fetch() -> object:
        return await HttpResourceFetcher(
            http_transport_factory=lambda: httpx.MockTransport(handle)
        ).fetch(source=source, resource=resource)

    result = asyncio.run(fetch())

    assert result.status == "FETCHED"
    assert result.content == b"literal"
