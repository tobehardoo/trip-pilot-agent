import asyncio
from datetime import UTC, datetime

import pytest

from trip_agent.acquisition.fetch_models import FetchValidators, ResourceFetched
from trip_agent.guide_intelligence.service import GuideImportService


class StubFetcher:
    def __init__(self, result: ResourceFetched) -> None:
        self.result = result
        self.source = None
        self.resource = None

    async def fetch(self, *, source, resource, validators=None):
        self.source = source
        self.resource = resource
        return self.result


def test_import_uses_single_host_allowlist_and_returns_traceable_result() -> None:
    fetched_at = datetime(2026, 7, 23, 8, 0, tzinfo=UTC)
    fetcher = StubFetcher(
        ResourceFetched(
            status="FETCHED",
            requested_url="https://example.com/post/1",
            final_url="https://example.com/post/1",
            fetched_at=fetched_at,
            content=(
                b"<html><title>Guide</title>"
                b"<article><p>Take metro line 2.</p></article></html>"
            ),
            content_type="text/html",
            validators=FetchValidators(),
        )
    )

    result = asyncio.run(
        GuideImportService(fetcher=fetcher).import_url(
            "https://example.com/post/1#comments"
        )
    )

    assert fetcher.source.allowed_domains == ("example.com",)
    assert fetcher.source.max_response_bytes == 2_000_000
    assert fetcher.resource.url == "https://example.com/post/1"
    assert result.source_url == "https://example.com/post/1"
    assert result.final_url == "https://example.com/post/1"
    assert len(result.content_hash) == 64
    assert result.fetched_at == fetched_at
    assert result.facts[0].category == "TRANSPORT"


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/post",
        "https://user:password@example.com/post",
        "https://localhost/post",
        "https://127.0.0.1/post",
    ],
)
def test_rejects_unsafe_user_urls_before_fetch(url: str) -> None:
    fetcher = StubFetcher(
        ResourceFetched(
            status="FETCHED",
            requested_url=url,
            final_url=url,
            fetched_at=datetime.now(UTC),
            content=b"",
            content_type="text/html",
            validators=FetchValidators(),
        )
    )

    with pytest.raises(ValueError):
        asyncio.run(GuideImportService(fetcher=fetcher).import_url(url))

    assert fetcher.source is None
