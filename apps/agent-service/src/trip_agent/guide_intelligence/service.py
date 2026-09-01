"""Application service for importing one user-submitted public guide URL."""

import asyncio
import base64
import hashlib
import logging
import math
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from typing import Protocol
from urllib.parse import urlsplit

import httpx

from trip_agent.acquisition.fetch_models import FetchResult, ResourceFetched
from trip_agent.acquisition.fetching import HttpResourceFetcher
from trip_agent.acquisition.models import DiscoveredResource, KnowledgeSource
from trip_agent.acquisition.security import SourceSecurityError, validate_source_url
from trip_agent.guide_intelligence.city_intelligence import AmapCityIntelligenceProvider
from trip_agent.guide_intelligence.extraction import GenericGuideExtractor
from trip_agent.guide_intelligence.models import ExtractedGuide, GuideImportResult, GuideSourceType
from trip_agent.guide_intelligence.ocr import (
    HttpVisionOcrProvider,
    ImagePayload,
    OcrError,
    ValidatedImage,
    configured_ocr_provider,
    configured_scan_extractor,
    configured_text_refiner,
    decode_and_validate_images,
    scan_fallback_enabled,
    sniff_image_format,
)
from trip_agent.guide_intelligence.qweather import QWeatherWeatherProvider
from trip_agent.guide_intelligence.structured_model import (
    ModelExtractionResult,
    StructuredModelFactExtractor,
    configured_structured_extractor,
)
from trip_agent.guide_intelligence.trusted_facts import (
    DocumentNormalizer,
    FactMerger,
    FactValidator,
    NormalizedDocument,
    RuleFactExtractor,
    ValidatedFact,
)

_TEXT_SOURCE_LABELS: dict[GuideSourceType, str] = {
    "PASTED_TEXT": "用户粘贴文本",
    "TEXT_FILE": "用户文本文件",
    "XIAOHONGSHU_SHARED_TEXT": "小红书分享文本",
    "IMAGE_OCR": "用户图片截图",
    "CITY_INTELLIGENCE": "和风天气城市情报",
    "PUBLIC_GUIDE_URL": "公开攻略链接",
}

_OCR_MIN_TEXT_CHARACTERS = 20
_OCR_MAX_CONCURRENCY = 3


@dataclass(frozen=True, slots=True)
class RecognizedImage:
    """One image's recognition outcome, including any fallback provenance."""

    text: str
    provider: str
    fallback_reason: str | None
    refined_by_llm: bool


def _looks_like_image(fetched: ResourceFetched) -> bool:
    if sniff_image_format(fetched.content) is not None:
        return True
    content_type = (fetched.content_type or "").casefold()
    return content_type.startswith("image/")

logger = logging.getLogger(__name__)


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
        structured_extractor: StructuredModelFactExtractor | None = None,
        ocr_provider: HttpVisionOcrProvider | None = None,
        scan_extractor: object | None = None,
        text_refiner: object | None = None,
    ) -> None:
        self._fetcher = fetcher or HttpResourceFetcher()
        self._extractor = extractor or GenericGuideExtractor()
        self._normalizer = DocumentNormalizer()
        self._rule_extractor = RuleFactExtractor()
        self._validator = FactValidator()
        self._merger = FactMerger()
        self._structured_extractor = structured_extractor
        self._ocr_provider = ocr_provider
        self._scan_extractor = scan_extractor
        self._text_refiner = text_refiner

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
            max_response_bytes=5_000_000,
        )
        resource = DiscoveredResource(
            source_id=source.source_id,
            city=source.city,
            url=normalized_url,
        )
        fetch_result = await self._fetcher.fetch(source=source, resource=resource)
        fetched = _require_fetched(fetch_result)
        if _looks_like_image(fetched):
            return await self._import_image_from_url(fetched, normalized_url, host)
        extracted = self._extractor.extract(
            content=fetched.content,
            content_type=fetched.content_type,
            fetched_at=fetched.fetched_at,
        )
        content_hash = hashlib.sha256(extracted.content.encode()).hexdigest()
        result = GuideImportResult(
            source_type="PUBLIC_GUIDE_URL",
            source_url=normalized_url,
            final_url=fetched.final_url,
            source_host=urlsplit(fetched.final_url).hostname or host,
            title=extracted.title,
            excerpt=extracted.content[:800],
            content_hash=content_hash,
            fetched_at=fetched.fetched_at,
            facts=extracted.facts,
        )
        document = self._normalizer.normalize_html(
            source_type="PUBLIC_GUIDE_URL",
            source_name=urlsplit(fetched.final_url).hostname or host,
            source_url=fetched.final_url,
            city="USER_TRIP",
            content=fetched.content,
            content_type=fetched.content_type,
            fetched_at=fetched.fetched_at,
            reliability_level="PUBLIC_GUIDE",
        )
        return await self._enrich(result, document)

    async def _import_image_from_url(
        self,
        fetched: ResourceFetched,
        normalized_url: str,
        host: str,
    ) -> GuideImportResult:
        """An image URL: same validation + OCR pipeline as uploaded screenshots."""
        payload = ImagePayload(
            dataBase64=base64.b64encode(fetched.content).decode("ascii")
        )
        (validated,) = decode_and_validate_images([payload])
        if self._ocr_provider is not None:
            recognized = await self._recognize_images(
                self._ocr_provider, (validated,)
            )
        else:
            async with httpx.AsyncClient(trust_env=False) as http_client:
                provider = configured_ocr_provider(http_client)
                if provider is None:
                    raise OcrError(
                        "OCR_NOT_CONFIGURED",
                        "图片识别未配置：请在服务端设置 OCR_MODEL_ENDPOINT、OCR_MODEL_API_KEY"
                        "和 OCR_MODEL_NAME 后重试，或改用粘贴正文导入。",
                    )
                recognized = await self._recognize_images(provider, (validated,))
        stripped = _require_usable_ocr_text(recognized[0].text)
        fetched_at = fetched.fetched_at
        final_host = urlsplit(fetched.final_url).hostname or host
        title = _derive_ocr_title(stripped)
        extracted = self._extractor.extract_text(
            title=title,
            content=stripped,
            fetched_at=fetched_at,
        )
        content_hash = hashlib.sha256(extracted.content.encode()).hexdigest()
        result = GuideImportResult(
            source_type="IMAGE_OCR",
            source_url=normalized_url,
            final_url=fetched.final_url,
            source_host=final_host,
            title=extracted.title,
            excerpt=extracted.content[:800],
            content_hash=content_hash,
            fetched_at=fetched_at,
            facts=extracted.facts,
        )
        document = self._normalizer.normalize_text(
            source_type="IMAGE_OCR",
            source_name=final_host,
            source_url=normalized_url,
            city="USER_TRIP",
            title=extracted.title,
            content=extracted.content,
            fetched_at=fetched_at,
            encoding="utf-8",
            reliability_level="COMMUNITY",
            metadata={
                "ocr": _ocr_metadata(
                    (validated,),
                    recognized,
                    image_url=normalized_url,
                )
            },
        )
        return await self._enrich(result, document)

    async def import_registered_source(
        self,
        *,
        source_url: str,
        source_name: str,
        source_type: GuideSourceType,
        city: str,
    ) -> GuideImportResult:
        if source_type not in {"OFFICIAL_TOURISM", "OFFICIAL_ATTRACTION"}:
            raise ValueError("registered source type must be official")
        host = _candidate_host(source_url)
        normalized_url = validate_source_url(source_url, allowed_domains=(host,))
        source = KnowledgeSource(
            source_id=f"registered-{hashlib.sha256(normalized_url.encode()).hexdigest()[:16]}",
            city=city.strip(),
            source_name=source_name.strip(),
            reliability_level="OFFICIAL",
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
        fetched = _require_fetched(
            await self._fetcher.fetch(source=source, resource=resource)
        )
        extracted = self._extractor.extract(
            content=fetched.content,
            content_type=fetched.content_type,
            fetched_at=fetched.fetched_at,
        )
        content_hash = hashlib.sha256(extracted.content.encode()).hexdigest()
        result = GuideImportResult(
            source_type=source_type,
            source_url=normalized_url,
            final_url=fetched.final_url,
            source_host=urlsplit(fetched.final_url).hostname or host,
            title=extracted.title,
            excerpt=extracted.content[:800],
            content_hash=content_hash,
            fetched_at=fetched.fetched_at,
            facts=extracted.facts,
        )
        document = self._normalizer.normalize_html(
            source_type=source_type,
            source_name=source.source_name,
            source_url=normalized_url,
            city=source.city,
            content=fetched.content,
            content_type=fetched.content_type,
            fetched_at=fetched.fetched_at,
            reliability_level=source_type,
            source_reviewed=True,
            metadata={
                "registryManaged": True,
                "finalUrl": fetched.final_url,
            },
        )
        return await self._enrich(result, document)

    def import_text(
        self,
        *,
        source_type: GuideSourceType,
        title: str,
        content: str,
        observed_at: datetime | None = None,
        document_metadata: Mapping[str, object] | None = None,
    ) -> GuideImportResult:
        if source_type in {
            "PUBLIC_GUIDE_URL",
            "CITY_INTELLIGENCE",
            "OFFICIAL_TOURISM",
            "OFFICIAL_ATTRACTION",
        }:
            raise ValueError("this source type cannot be imported as user text")
        fetched_at = observed_at or datetime.now(UTC)
        extracted = self._extractor.extract_text(
            title=title,
            content=content,
            fetched_at=fetched_at,
        )
        content_hash = hashlib.sha256(extracted.content.encode()).hexdigest()
        source_url = (
            "https://user-content.trippilot.invalid/"
            f"{source_type.casefold().replace('_', '-')}/{content_hash[:24]}"
        )
        result = GuideImportResult(
            source_type=source_type,
            source_url=source_url,
            final_url=source_url,
            source_host=_TEXT_SOURCE_LABELS[source_type],
            title=extracted.title,
            excerpt=extracted.content[:800],
            content_hash=content_hash,
            fetched_at=fetched_at,
            facts=extracted.facts,
        )
        document = self._normalizer.normalize_text(
            source_type=source_type,
            source_name=_TEXT_SOURCE_LABELS[source_type],
            source_url=source_url,
            city="USER_TRIP",
            title=extracted.title,
            content=extracted.content,
            fetched_at=fetched_at,
            encoding="utf-8",
            reliability_level="COMMUNITY",
            metadata=document_metadata,
        )
        return self._enrich_rules(result, document)

    async def import_images(
        self,
        *,
        images: list[ImagePayload] | None,
        observed_at: datetime | None = None,
    ) -> GuideImportResult:
        validated_images = decode_and_validate_images(images)
        # Keep the HTTP client that backs an env-configured provider open
        # for the entire recognition phase; closing it early surfaces as
        # "client has been closed" in production.
        if self._ocr_provider is not None:
            recognized = await self._recognize_images(
                self._ocr_provider, validated_images
            )
        else:
            async with httpx.AsyncClient(trust_env=False) as http_client:
                provider = configured_ocr_provider(http_client)
                if provider is None:
                    raise OcrError(
                        "OCR_NOT_CONFIGURED",
                        "图片识别未配置：请在服务端设置 OCR_MODEL_ENDPOINT、OCR_MODEL_API_KEY"
                        "和 OCR_MODEL_NAME 后重试，或改用粘贴正文导入。",
                    )
                recognized = await self._recognize_images(provider, validated_images)
        ocr_text = "\n\n".join(item.text for item in recognized if item.text)
        stripped = _require_usable_ocr_text(ocr_text)
        fetched_at = observed_at or datetime.now(UTC)
        result = self.import_text(
            source_type="IMAGE_OCR",
            title=_derive_ocr_title(stripped),
            content=stripped,
            observed_at=fetched_at,
            document_metadata={
                "ocr": _ocr_metadata(validated_images, recognized),
            },
        )
        if result.normalized_document is None:
            raise AssertionError("image OCR normalization must produce a document")
        return await self._enrich(result, result.normalized_document)

    async def _recognize_images(
        self,
        provider: HttpVisionOcrProvider,
        images: tuple[ValidatedImage, ...],
    ) -> list[RecognizedImage]:
        """Recognize each image with vision first, then the scan fallback.

        A lazily resolved provider shares one HTTP client with its transport;
        that client must stay open until every recognition request finishes,
        so resolution happens before any recognition starts.
        """
        semaphore = asyncio.Semaphore(_OCR_MAX_CONCURRENCY)

        async def recognize(image: ValidatedImage) -> RecognizedImage:
            async with semaphore:
                return await self._recognize_one(provider, image)

        return list(await asyncio.gather(*(recognize(image) for image in images)))

    async def _recognize_one(
        self,
        provider: HttpVisionOcrProvider,
        image: ValidatedImage,
    ) -> RecognizedImage:
        try:
            text = await provider.recognize(image)
            return RecognizedImage(
                text=text,
                provider="vision_model",
                fallback_reason=None,
                refined_by_llm=False,
            )
        except OcrError as error:
            if error.code not in {"OCR_FAILED", "OCR_TIMEOUT"}:
                raise
            if not scan_fallback_enabled():
                raise
            scan = self._scan_extractor
            if scan is None:
                scan = configured_scan_extractor()
            if scan is None:
                raise
            raw_scan = (await scan.extract_text(image)).strip()
            refined, refined_by_llm = await self._refine_scan_text(
                raw_scan, error.code
            )
            return RecognizedImage(
                text=refined,
                provider="scan_fallback",
                fallback_reason=error.code,
                refined_by_llm=refined_by_llm,
            )

    async def _refine_scan_text(
        self,
        raw_scan: str,
        fallback_reason: str,
    ) -> tuple[str, bool]:
        refiner = self._text_refiner
        if refiner is None:
            async with httpx.AsyncClient(trust_env=False) as http_client:
                refiner = configured_text_refiner(http_client)
        if refiner is None:
            return raw_scan, False
        try:
            refined = await refiner.refine(raw_scan)
        except (
            TimeoutError,
            httpx.TimeoutException,
            httpx.HTTPError,
            KeyError,
            IndexError,
            TypeError,
            ValueError,
        ):
            logger.warning(
                "ocr_scan_refinement_failed fallback_reason=%s", fallback_reason
            )
            return raw_scan, False
        return (refined.strip() or raw_scan), bool(refined.strip())

    async def import_text_with_model(
        self,
        *,
        source_type: GuideSourceType,
        title: str,
        content: str,
        observed_at: datetime | None = None,
    ) -> GuideImportResult:
        result = self.import_text(
            source_type=source_type,
            title=title,
            content=content,
            observed_at=observed_at,
        )
        if result.normalized_document is None:
            raise AssertionError("text normalization must produce a document")
        return await self._enrich(result, result.normalized_document)

    async def import_city(
        self,
        *,
        city: str,
        start_date: date,
        end_date: date,
    ) -> GuideImportResult:
        amap_api_key = os.getenv("AMAP_WEB_SERVICE_KEY", "").strip()
        qweather_api_key = os.getenv("QWEATHER_API_KEY", "").strip()
        qweather_api_host = os.getenv("QWEATHER_API_HOST", "").strip()
        if bool(qweather_api_key) != bool(qweather_api_host):
            raise RuntimeError(
                "QWEATHER_API_KEY and QWEATHER_API_HOST must be configured together"
            )
        use_qweather = bool(qweather_api_key)
        weather_provider = "QWEATHER" if use_qweather else "AMAP"
        weather_fallback_reason: str | None = None
        location_fallback_reason: str | None = None
        poi_provider: str | None = None
        poi_unavailable_reason: str | None = None
        if not use_qweather and not amap_api_key:
            raise RuntimeError(
                "AMAP_WEB_SERVICE_KEY or both QWEATHER_API_KEY and QWEATHER_API_HOST are required"
            )
        fetched_at = datetime.now(UTC)
        async with httpx.AsyncClient(timeout=httpx.Timeout(8.0)) as http_client:
            amap_provider = (
                AmapCityIntelligenceProvider(
                    api_key=amap_api_key,
                    http_client=http_client,
                )
                if amap_api_key
                else None
            )
            if use_qweather:
                location_query = city
                if amap_provider is not None:
                    try:
                        location_query = _qweather_location_query(
                            await amap_provider.resolve_city_location(city)
                        )
                    except (RuntimeError, ValueError) as error:
                        location_fallback_reason = str(error)
                        logger.warning(
                            "amap_location_enrichment_unavailable city=%s reason=%s",
                            city,
                            location_fallback_reason,
                        )
                try:
                    weather = await QWeatherWeatherProvider(
                        api_key=qweather_api_key,
                        http_client=http_client,
                        api_host=qweather_api_host,
                    ).collect(
                        city=city,
                        start_date=start_date,
                        end_date=end_date,
                        checked_at=fetched_at,
                        location_query=location_query,
                    )
                except (RuntimeError, ValueError) as error:
                    if amap_provider is None:
                        raise
                    weather_fallback_reason = str(error)
                    weather_provider = "AMAP"
                    logger.warning(
                        "qweather_city_import_fallback city=%s reason=%s",
                        city,
                        weather_fallback_reason,
                    )
                    weather = await amap_provider.collect(
                        city=city,
                        start_date=start_date,
                        end_date=end_date,
                        checked_at=fetched_at,
                    )
                    poi_provider = "AMAP"
                extracted = weather
                if amap_provider is not None and weather_provider == "QWEATHER":
                    try:
                        amap = await amap_provider.collect(
                            city=city,
                            start_date=start_date,
                            end_date=end_date,
                            checked_at=fetched_at,
                        )
                    except (RuntimeError, ValueError) as error:
                        poi_unavailable_reason = str(error)
                        logger.warning(
                            "amap_city_enrichment_unavailable city=%s reason=%s",
                            city,
                            poi_unavailable_reason,
                        )
                    else:
                        poi_provider = "AMAP"
                        poi_facts = tuple(
                            fact for fact in amap.facts if fact.category != "WEATHER"
                        )
                        extracted = ExtractedGuide(
                            title=weather.title,
                            content="\n".join(
                                (weather.content, *(fact.statement for fact in poi_facts))
                            ),
                            facts=(*weather.facts, *poi_facts),
                            source_url=weather.source_url,
                        )
            else:
                if amap_provider is None:
                    raise AssertionError("AMap provider must be configured for the fallback")
                extracted = await amap_provider.collect(
                    city=city,
                    start_date=start_date,
                    end_date=end_date,
                    checked_at=fetched_at,
                )
                poi_provider = "AMAP"
        content_hash = hashlib.sha256(extracted.content.encode()).hexdigest()
        normalized_city = city.strip()
        qweather_source_url = extracted.source_url or "https://www.qweather.com"
        source_url = (
            qweather_source_url
            if weather_provider == "QWEATHER"
            else "https://lbs.amap.com/api/webservice/guide/api/weatherinfo"
            f"#trip-pilot-city={normalized_city}"
        )
        if weather_provider == "QWEATHER" and poi_provider == "AMAP":
            source_name = "和风天气（天气）+ 高德（城市地点）"
        elif weather_provider == "QWEATHER":
            source_name = "和风天气城市情报"
        else:
            source_name = "高德城市情报"
        provider_sources = {"WEATHER": weather_provider}
        if poi_provider is not None:
            provider_sources["NON_WEATHER"] = poi_provider
        result = GuideImportResult(
            source_type="CITY_INTELLIGENCE",
            source_url=source_url,
            final_url=source_url,
            source_host=source_name,
            title=extracted.title,
            excerpt=extracted.content[:800],
            content_hash=content_hash,
            fetched_at=fetched_at,
            facts=extracted.facts,
        )
        document = self._normalizer.normalize_structured(
            source_type="CITY_INTELLIGENCE",
            source_name=source_name,
            source_url=source_url,
            city=normalized_city,
            title=extracted.title,
            content=extracted.content,
            fetched_at=fetched_at,
            reliability_level=(
                "WEATHER_PROVIDER" if weather_provider == "QWEATHER" else "MAP_PROVIDER"
            ),
            metadata={
                "weatherProvider": weather_provider,
                "weatherFallbackReason": weather_fallback_reason,
                "locationFallbackReason": location_fallback_reason,
                "poiProvider": poi_provider,
                "poiUnavailableReason": poi_unavailable_reason,
                "providerSources": provider_sources,
                "providerSourceUrls": {
                    "QWEATHER": qweather_source_url,
                    "AMAP": "https://lbs.amap.com/api/webservice/guide/api/search",
                },
                "startDate": start_date.isoformat(),
                "endDate": end_date.isoformat(),
            },
        )
        return await self._enrich(
            result,
            document,
            fact_transform=lambda fact: _with_city_provider_provenance(
                fact,
                weather_provider=weather_provider,
                poi_provider=poi_provider,
                qweather_source_url=qweather_source_url,
            ),
        )

    def _enrich_rules(
        self,
        result: GuideImportResult,
        document: NormalizedDocument,
    ) -> GuideImportResult:
        candidates = self._rule_extractor.extract(
            document,
            checked_at=result.fetched_at,
        )
        validation = self._validator.validate(document, candidates)
        merge = self._merger.merge(validation.accepted)
        return replace(
            result,
            normalized_document=document,
            trusted_facts=merge.selected_facts,
            rejected_facts=validation.rejected,
            merge_decisions=merge.decisions,
            model_extraction=ModelExtractionResult(
                status="SKIPPED",
                candidates=(),
                attempts=0,
                failure_code="MODEL_NOT_RUN",
                failure_reason="only deterministic extraction was requested",
            ),
        )

    async def _enrich(
        self,
        result: GuideImportResult,
        document: NormalizedDocument,
        *,
        fact_transform: Callable[[ValidatedFact], ValidatedFact] | None = None,
    ) -> GuideImportResult:
        rule_candidates = self._rule_extractor.extract(
            document,
            checked_at=result.fetched_at,
        )
        model_result = await self._extract_model(document, result.fetched_at)
        all_candidates = (*rule_candidates, *model_result.candidates)
        security = _apply_security_filter(all_candidates)
        validation = self._validator.validate(
            document,
            security.passed,
        )
        accepted = (
            tuple(fact_transform(fact) for fact in validation.accepted)
            if fact_transform is not None
            else validation.accepted
        )
        merge = self._merger.merge(accepted)
        enriched = replace(
            result,
            normalized_document=document,
            trusted_facts=merge.selected_facts,
            rejected_facts=(
                *security.rejected,
                *validation.rejected,
            ),
            merge_decisions=merge.decisions,
            model_extraction=model_result,
        )
        from trip_agent.guide_intelligence.quality import compute_guide_quality  # noqa: PLC0415

        return replace(enriched, quality=compute_guide_quality(enriched))
    async def _extract_model(
        self,
        document: NormalizedDocument,
        checked_at: datetime,
    ) -> ModelExtractionResult:
        if self._structured_extractor is not None:
            return await self._structured_extractor.extract(
                document,
                checked_at=checked_at,
            )
        async with httpx.AsyncClient(trust_env=False) as http_client:
            return await configured_structured_extractor(http_client).extract(
                document,
                checked_at=checked_at,
            )


def _require_usable_ocr_text(ocr_text: str) -> str:
    stripped = ocr_text.strip()
    if not stripped:
        raise OcrError(
            "OCR_NO_TEXT",
            "未能从图片中识别出文字。请确认截图清晰、包含攻略正文后重试，"
            "或改用粘贴正文导入。",
        )
    if len(stripped) < _OCR_MIN_TEXT_CHARACTERS:
        raise OcrError(
            "OCR_TEXT_TOO_SHORT",
            "识别出的文字太少，请上传包含完整攻略正文的清晰截图。",
        )
    return stripped


def _ocr_metadata(
    images: tuple[ValidatedImage, ...],
    recognized: list[RecognizedImage],
    *,
    image_url: str | None = None,
) -> dict[str, object]:
    providers = {item.provider for item in recognized}
    fallback_reasons = [
        item.fallback_reason for item in recognized if item.fallback_reason
    ]
    metadata: dict[str, object] = {
        "provider": providers.pop() if len(providers) == 1 else "mixed",
        "refinedByLLM": all(item.refined_by_llm for item in recognized),
        "imageCount": len(images),
        "images": [
            {
                "sha256": image.sha256,
                "format": image.format,
                "width": image.width,
                "height": image.height,
            }
            for image in images
        ],
    }
    if fallback_reasons:
        metadata["fallbackReason"] = fallback_reasons[0]
    if image_url is not None:
        metadata["imageUrl"] = image_url
    return metadata


def _derive_ocr_title(ocr_text: str) -> str:
    for line in ocr_text.splitlines():
        normalized = line.strip()
        if not normalized:
            continue
        return normalized[:60]
    return f"图片攻略 {date.today().isoformat()}"


def _qweather_location_query(center: str) -> str:
    parts = [part.strip() for part in center.split(",")]
    if len(parts) != 2:
        raise ValueError("AMap city center must contain longitude and latitude")
    try:
        longitude, latitude = (float(part) for part in parts)
    except ValueError as error:
        raise ValueError("AMap city center must contain numeric coordinates") from error
    if not math.isfinite(longitude) or not math.isfinite(latitude):
        raise ValueError("AMap city center coordinates must be finite")
    if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
        raise ValueError("AMap city center coordinates are outside valid bounds")
    return f"{longitude:.2f},{latitude:.2f}"


def _with_city_provider_provenance(
    fact: ValidatedFact,
    *,
    weather_provider: str,
    poi_provider: str | None,
    qweather_source_url: str,
) -> ValidatedFact:
    provider = weather_provider if fact.category == "WEATHER" else poi_provider
    if provider == "QWEATHER":
        return replace(
            fact,
            source_name="和风天气城市情报",
            source_url=qweather_source_url,
            reliability_level="WEATHER_PROVIDER",
        )
    if provider == "AMAP":
        return replace(
            fact,
            source_name="高德城市情报",
            source_url=(
                "https://lbs.amap.com/api/webservice/guide/api/weatherinfo"
                if fact.category == "WEATHER"
                else "https://lbs.amap.com/api/webservice/guide/api/search"
            ),
            reliability_level="MAP_PROVIDER",
        )
    return fact


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


@dataclass(frozen=True, slots=True)
class _SecurityFilterResult:
    passed: tuple
    rejected: tuple


def _apply_security_filter(
    candidates: tuple,
) -> _SecurityFilterResult:
    from trip_agent.guide_intelligence.security_filter import filter_content  # noqa: PLC0415
    from trip_agent.guide_intelligence.trusted_facts import (  # noqa: PLC0415
        RejectedFact,
        ValidationReason,
    )

    result = filter_content(candidates)
    return _SecurityFilterResult(
        passed=result.passed,
        rejected=tuple(
            RejectedFact(
                candidate=blocked.candidate,
                reasons=(ValidationReason(code=blocked.rule, message=blocked.detail),),
            )
            for blocked in result.blocked
        ),
    )


def _require_fetched(result: FetchResult) -> ResourceFetched:
    if result.status != "FETCHED":
        raise RuntimeError("an unconditional guide request unexpectedly returned not modified")
    return result
