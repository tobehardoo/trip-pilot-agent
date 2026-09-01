import asyncio
from datetime import UTC, datetime

import httpx
import pytest

from trip_agent.providers.errors import ProviderErrorCategory, ProviderOperation
from trip_agent.providers.map import AmapMapProvider, PoiSearchRequest, ProviderFailure
from trip_agent.providers.route import AmapRouteProvider, Coordinates, RouteRequest


async def _search(handler: object) -> ProviderFailure:
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await AmapMapProvider(
            api_key="local-test-key",
            http_client=client,
        ).search_pois(PoiSearchRequest(city="Guangzhou", keyword="museum"))
    assert isinstance(result, ProviderFailure)
    return result


async def _route(handler: object) -> ProviderFailure:
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await AmapRouteProvider(
            api_key="local-test-key",
            http_client=client,
        ).get_route(
            RouteRequest(
                origin=Coordinates(longitude=113.3, latitude=23.1),
                destination=Coordinates(longitude=113.4, latitude=23.2),
                departure_at=datetime(2026, 8, 1, tzinfo=UTC),
                mode="WALKING",
            )
        )
    assert isinstance(result, ProviderFailure)
    return result


@pytest.mark.parametrize(
    ("infocode", "category", "retryable"),
    [
        ("10001", ProviderErrorCategory.AUTHENTICATION_ERROR, False),
        ("10006", ProviderErrorCategory.PERMISSION_DENIED, False),
        ("10003", ProviderErrorCategory.QUOTA_EXCEEDED, False),
        ("10004", ProviderErrorCategory.RATE_LIMITED, True),
        ("10017", ProviderErrorCategory.PROVIDER_UNAVAILABLE, True),
        ("20000", ProviderErrorCategory.INVALID_REQUEST, False),
    ],
)
def test_amap_infocode_is_safely_preserved_with_stable_classification(
    infocode: str,
    category: ProviderErrorCategory,
    retryable: bool,
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"status": "0", "info": "rejected", "infocode": infocode},
        )

    failure = asyncio.run(_search(handler))

    assert failure.category == category
    assert failure.operation == ProviderOperation.POI_SEARCH
    assert failure.retryable is retryable
    assert failure.safe_provider_code == infocode
    assert "local-test-key" not in failure.error_message


def test_http_rate_limit_preserves_retry_after_without_response_body() -> None:
    failure = asyncio.run(
        _search(lambda _: httpx.Response(429, headers={"Retry-After": "1.25"}))
    )

    assert failure.category == ProviderErrorCategory.RATE_LIMITED
    assert failure.safe_provider_code == "HTTP_429"
    assert failure.retry_after_seconds == 1.25


def test_network_and_malformed_response_have_distinct_categories() -> None:
    def disconnected(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection failed", request=request)

    network = asyncio.run(_search(disconnected))
    malformed = asyncio.run(_search(lambda _: httpx.Response(200, content=b"not-json")))

    assert network.category == ProviderErrorCategory.NETWORK_ERROR
    assert network.cause_type == "ConnectError"
    assert malformed.category == ProviderErrorCategory.MALFORMED_RESPONSE
    assert malformed.retryable is True


@pytest.mark.parametrize(
    ("status_code", "category", "retryable"),
    [
        (400, ProviderErrorCategory.INVALID_REQUEST, False),
        (401, ProviderErrorCategory.AUTHENTICATION_ERROR, False),
        (403, ProviderErrorCategory.PERMISSION_DENIED, False),
        (503, ProviderErrorCategory.PROVIDER_UNAVAILABLE, True),
    ],
)
def test_http_statuses_have_stable_safe_classification(
    status_code: int,
    category: ProviderErrorCategory,
    retryable: bool,
) -> None:
    failure = asyncio.run(_search(lambda _: httpx.Response(status_code)))

    assert failure.category == category
    assert failure.retryable is retryable
    assert failure.safe_provider_code == f"HTTP_{status_code}"


def test_empty_poi_results_are_local_no_result_not_malformed() -> None:
    failure = asyncio.run(
        _search(
            lambda _: httpx.Response(
                200,
                json={
                    "status": "1",
                    "info": "OK",
                    "infocode": "10000",
                    "pois": [],
                },
            )
        )
    )

    assert failure.category == ProviderErrorCategory.NO_RESULT
    assert failure.retryable is False


@pytest.mark.parametrize(
    ("infocode", "category", "retryable"),
    [
        ("10001", ProviderErrorCategory.AUTHENTICATION_ERROR, False),
        ("10006", ProviderErrorCategory.PERMISSION_DENIED, False),
        ("10003", ProviderErrorCategory.QUOTA_EXCEEDED, False),
        ("10004", ProviderErrorCategory.RATE_LIMITED, True),
        ("10017", ProviderErrorCategory.PROVIDER_UNAVAILABLE, True),
        ("20000", ProviderErrorCategory.INVALID_REQUEST, False),
    ],
)
def test_route_business_failures_preserve_infocode_and_category(
    infocode: str,
    category: ProviderErrorCategory,
    retryable: bool,
) -> None:
    failure = asyncio.run(
        _route(
            lambda _: httpx.Response(
                200,
                json={"status": "0", "info": "rejected", "infocode": infocode},
            )
        )
    )

    assert failure.category == category
    assert failure.operation == ProviderOperation.ROUTE
    assert failure.retryable is retryable
    assert failure.safe_provider_code == infocode


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"not-json"),
        httpx.Response(
            200,
            json={"status": "1", "info": "OK", "infocode": "10000"},
        ),
    ],
)
def test_route_malformed_responses_never_become_demo_or_no_result(
    response: httpx.Response,
) -> None:
    failure = asyncio.run(_route(lambda _: response))

    assert failure.category == ProviderErrorCategory.MALFORMED_RESPONSE
    assert failure.retryable is True
