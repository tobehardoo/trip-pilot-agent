"""Application service for importing one user-submitted public guide URL."""

import hashlib
from typing import Protocol
from urllib.parse import urlsplit

from trip_agent.acquisition.fetch_models import FetchResult, ResourceFetched
from trip_agent.acquisition.fetching import HttpResourceFetcher
from trip_agent.acquisition.models import DiscoveredResource, KnowledgeSource
from trip_agent.acquisition.security import SourceSecurityError, validate_source_url
from trip_agent.guide_intelligence.extraction import GenericGuideExtractor
from trip_agent.guide_intelligence.models import GuideImportResult


class GuideFetcher(Protocol):
    async def fetch(
        self,
        *,
        source: KnowledgeSource,
        resource: DiscoveredResource,
        validators: object | None = None,
    ) -> FetchResult: ...


class GuideImportService:
    def __init__(
        self,
        *,
        fetcher: GuideFetcher | None = None,
        extractor: GenericGuideExtractor | None = None,
    ) -> None:
        self._fetcher = fetcher or HttpResourceFetcher()
        self._extractor = extractor or GenericGuideExtractor()

    async def import_url(self, source_url: str) -> GuideImportResult:
        host = _candidate_host(source_url)
        normalized_url = validate_source_url(source_url, allowed_domains=(host,))
        source_id = f"user-guide-{hashlib.sha256(host.encode()).hexdigest()[:16]}"
        source = KnowledgeSource(
            source_id=source_id,
            city="USER_TRIP",
            source_name=host,
            reliability_level="COMMUNITY",
            allowed_domains=(host,),
            resource_urls=(normalized_url,),
            min_request_interval_seconds=1.0,
            request_timeout_seconds=12.0,
            max_response_bytes=2_000_000,
        )
        resource = DiscoveredResource(
            source_id=source.source_id,
            city=source.city,
            url=normalized_url,
        )
        fetch_result = await self._fetcher.fetch(source=source, resource=resource)
        fetched = _require_fetched(fetch_result)
        extracted = self._extractor.extract(
            content=fetched.content,
            content_type=fetched.content_type,
            fetched_at=fetched.fetched_at,
        )
        content_hash = hashlib.sha256(extracted.content.encode()).hexdigest()
        return GuideImportResult(
            source_url=normalized_url,
            final_url=fetched.final_url,
            source_host=urlsplit(fetched.final_url).hostname or host,
            title=extracted.title,
            excerpt=extracted.content[:800],
            content_hash=content_hash,
            fetched_at=fetched.fetched_at,
            facts=extracted.facts,
        )


def _candidate_host(source_url: str) -> str:
    if not isinstance(source_url, str) or not source_url.strip():
        raise SourceSecurityError("source URL cannot be empty")
    parsed = urlsplit(source_url.strip())
    if parsed.username is not None or parsed.password is not None:
        raise SourceSecurityError("source URL cannot contain credentials")
    hostname = parsed.hostname
    if hostname is None:
        raise SourceSecurityError("source URL must contain a hostname")
    try:
        return hostname.encode("idna").decode("ascii").lower().rstrip(".")
    except UnicodeError as error:
        raise SourceSecurityError("source URL hostname is invalid") from error


def _require_fetched(result: FetchResult) -> ResourceFetched:
    if result.status != "FETCHED":
        raise RuntimeError("an unconditional guide request unexpectedly returned not modified")
    return result
