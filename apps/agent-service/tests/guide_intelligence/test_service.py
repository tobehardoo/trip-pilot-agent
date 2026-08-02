import asyncio
from datetime import UTC, date, datetime, timedelta

import pytest

from trip_agent.acquisition.fetch_models import FetchValidators, ResourceFetched
from trip_agent.guide_intelligence import service as service_module
from trip_agent.guide_intelligence.models import (
    ExtractedGuide,
    FactCategory,
    TravelFact,
)
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


def _fact(category: FactCategory, statement: str) -> TravelFact:
    observed_at = datetime(2026, 8, 2, 8, 0, tzinfo=UTC)
    return TravelFact(
        category=category,
        statement=statement,
        evidence=statement,
        confidence=0.9,
        observed_at=observed_at,
        expires_at=observed_at + timedelta(days=1),
        effective_date=date(2026, 8, 2),
    )


class StubAmapCityProvider:
    location_should_fail = False
    collect_should_fail = False
    location_result = "113.27,23.13"

    def __init__(self, **_: object) -> None:
        self.collect_calls = 0

    async def resolve_city_location(self, city: str) -> str:
        assert city == "广州"
        if self.location_should_fail:
            raise RuntimeError("AMap location lookup failed")
        return self.location_result

    async def collect(self, **_: object) -> ExtractedGuide:
        if self.collect_should_fail:
            raise RuntimeError("AMap city intelligence failed")
        self.collect_calls += 1
        return ExtractedGuide(
            title="高德城市情报",
            content="广州当前天气：阵雨，28℃。陈家祠地址是中山七路。",
            facts=(
                _fact("WEATHER", "高德天气"),
                _fact("ATTRACTION", "陈家祠地址是中山七路"),
            ),
        )


class StubQWeatherProvider:
    should_fail = False
    last_location_query: str | None = None

    def __init__(self, **_: object) -> None:
        pass

    async def collect(self, **kwargs: object) -> ExtractedGuide:
        type(self).last_location_query = str(kwargs["location_query"])
        if self.should_fail:
            raise RuntimeError("QWeather request timed out")
        return ExtractedGuide(
            title="和风天气城市情报",
            content="广州当前天气：晴，30℃。",
            facts=(_fact("WEATHER", "和风天气晴"),),
        )


def _configure_city_providers(
    monkeypatch: pytest.MonkeyPatch,
    *,
    amap: bool,
    qweather: bool,
) -> None:
    monkeypatch.setenv("AMAP_WEB_SERVICE_KEY", "amap-key" if amap else "")
    monkeypatch.setenv("QWEATHER_API_KEY", "qweather-key" if qweather else "")
    monkeypatch.setenv("QWEATHER_API_HOST", "weather.example.com" if qweather else "")
    monkeypatch.setattr(
        service_module,
        "AmapCityIntelligenceProvider",
        StubAmapCityProvider,
    )
    monkeypatch.setattr(
        service_module,
        "QWeatherWeatherProvider",
        StubQWeatherProvider,
    )
    StubAmapCityProvider.location_should_fail = False
    StubAmapCityProvider.collect_should_fail = False
    StubAmapCityProvider.location_result = "113.27,23.13"
    StubQWeatherProvider.last_location_query = None


def test_import_city_combines_qweather_with_amap_non_weather_facts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_city_providers(monkeypatch, amap=True, qweather=True)
    StubQWeatherProvider.should_fail = False

    result = asyncio.run(
        GuideImportService().import_city(
            city="广州",
            start_date=date(2026, 8, 2),
            end_date=date(2026, 8, 4),
        )
    )

    assert [fact.statement for fact in result.facts] == [
        "和风天气晴",
        "陈家祠地址是中山七路",
    ]
    assert result.normalized_document is not None
    assert result.normalized_document.metadata["weatherProvider"] == "QWEATHER"
    assert result.normalized_document.metadata["poiProvider"] == "AMAP"
    assert result.source_host == "和风天气（天气）+ 高德（城市地点）"
    assert result.normalized_document.metadata["providerSources"] == {
        "WEATHER": "QWEATHER",
        "NON_WEATHER": "AMAP",
    }
    assert "阵雨" not in result.normalized_document.content
    trusted_weather = [fact for fact in result.trusted_facts if fact.category == "WEATHER"]
    assert len(trusted_weather) == 1
    assert trusted_weather[0].source_name == "和风天气城市情报"
    assert trusted_weather[0].source_url == "https://dev.qweather.com/en/docs/api/"
    trusted_addresses = [fact for fact in result.trusted_facts if fact.category == "ADDRESS"]
    assert len(trusted_addresses) == 1
    assert trusted_addresses[0].source_name == "高德城市情报"
    assert trusted_addresses[0].source_url == (
        "https://lbs.amap.com/api/webservice/guide/api/search"
    )
    assert trusted_addresses[0].reliability_level == "MAP_PROVIDER"


def test_import_city_keeps_qweather_when_amap_enrichment_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_city_providers(monkeypatch, amap=True, qweather=True)
    StubAmapCityProvider.location_should_fail = True
    StubAmapCityProvider.collect_should_fail = True
    StubQWeatherProvider.should_fail = False

    result = asyncio.run(
        GuideImportService().import_city(
            city="广州",
            start_date=date(2026, 8, 2),
            end_date=date(2026, 8, 4),
        )
    )

    assert [fact.statement for fact in result.facts] == ["和风天气晴"]
    assert result.source_host == "和风天气城市情报"
    assert result.normalized_document is not None
    assert result.normalized_document.metadata["weatherProvider"] == "QWEATHER"
    assert result.normalized_document.metadata["poiProvider"] is None
    assert result.normalized_document.metadata["poiUnavailableReason"] == (
        "AMap city intelligence failed"
    )


def test_import_city_uses_qweather_city_lookup_when_amap_location_resolution_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_city_providers(monkeypatch, amap=True, qweather=True)
    StubAmapCityProvider.location_should_fail = True
    StubQWeatherProvider.should_fail = False

    result = asyncio.run(
        GuideImportService().import_city(
            city="广州",
            start_date=date(2026, 8, 2),
            end_date=date(2026, 8, 4),
        )
    )

    assert StubQWeatherProvider.last_location_query == "广州"
    assert result.normalized_document is not None
    assert result.normalized_document.metadata["weatherProvider"] == "QWEATHER"


def test_import_city_rounds_amap_center_for_qweather_city_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_city_providers(monkeypatch, amap=True, qweather=True)
    StubAmapCityProvider.location_result = "113.270123,23.130456"
    StubQWeatherProvider.should_fail = False

    asyncio.run(
        GuideImportService().import_city(
            city="广州",
            start_date=date(2026, 8, 2),
            end_date=date(2026, 8, 4),
        )
    )

    assert StubQWeatherProvider.last_location_query == "113.27,23.13"


def test_import_city_uses_amap_when_qweather_is_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_city_providers(monkeypatch, amap=True, qweather=False)

    result = asyncio.run(
        GuideImportService().import_city(
            city="广州",
            start_date=date(2026, 8, 2),
            end_date=date(2026, 8, 4),
        )
    )

    assert {fact.statement for fact in result.facts} == {
        "高德天气",
        "陈家祠地址是中山七路",
    }
    assert result.source_host == "高德城市情报"
    assert result.normalized_document is not None
    assert result.normalized_document.metadata["weatherProvider"] == "AMAP"


def test_import_city_uses_qweather_without_amap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_city_providers(monkeypatch, amap=False, qweather=True)
    StubQWeatherProvider.should_fail = False

    result = asyncio.run(
        GuideImportService().import_city(
            city="广州",
            start_date=date(2026, 8, 2),
            end_date=date(2026, 8, 4),
        )
    )

    assert [fact.statement for fact in result.facts] == ["和风天气晴"]
    assert result.source_host == "和风天气城市情报"
    assert result.normalized_document is not None
    assert result.normalized_document.metadata["weatherProvider"] == "QWEATHER"
    assert result.normalized_document.metadata["poiProvider"] is None


def test_import_city_falls_back_to_amap_when_qweather_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_city_providers(monkeypatch, amap=True, qweather=True)
    StubQWeatherProvider.should_fail = True

    result = asyncio.run(
        GuideImportService().import_city(
            city="广州",
            start_date=date(2026, 8, 2),
            end_date=date(2026, 8, 4),
        )
    )

    assert {fact.statement for fact in result.facts} == {
        "高德天气",
        "陈家祠地址是中山七路",
    }
    assert result.source_host == "高德城市情报"
    assert result.normalized_document is not None
    assert result.normalized_document.metadata["weatherProvider"] == "AMAP"
    assert result.normalized_document.metadata["weatherFallbackReason"] == (
        "QWeather request timed out"
    )


def test_import_city_requires_complete_qweather_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AMAP_WEB_SERVICE_KEY", "")
    monkeypatch.setenv("QWEATHER_API_KEY", "qweather-key")
    monkeypatch.setenv("QWEATHER_API_HOST", "")

    with pytest.raises(
        RuntimeError,
        match="QWEATHER_API_KEY and QWEATHER_API_HOST must be configured together",
    ):
        asyncio.run(
            GuideImportService().import_city(
                city="广州",
                start_date=date(2026, 8, 2),
                end_date=date(2026, 8, 4),
            )
        )


@pytest.mark.parametrize(
    ("api_key", "api_host"),
    [
        ("qweather-key", ""),
        ("", "weather.example.com"),
    ],
)
def test_import_city_rejects_partial_qweather_configuration_even_with_amap(
    monkeypatch: pytest.MonkeyPatch,
    api_key: str,
    api_host: str,
) -> None:
    monkeypatch.setenv("AMAP_WEB_SERVICE_KEY", "amap-key")
    monkeypatch.setenv("QWEATHER_API_KEY", api_key)
    monkeypatch.setenv("QWEATHER_API_HOST", api_host)

    with pytest.raises(
        RuntimeError,
        match="QWEATHER_API_KEY and QWEATHER_API_HOST must be configured together",
    ):
        asyncio.run(
            GuideImportService().import_city(
                city="广州",
                start_date=date(2026, 8, 2),
                end_date=date(2026, 8, 4),
            )
        )


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


def test_import_text_does_not_fetch_and_returns_a_traceable_local_source() -> None:
    fetched_at = datetime(2026, 7, 26, 8, 0, tzinfo=UTC)
    fetcher = StubFetcher(
        ResourceFetched(
            status="FETCHED",
            requested_url="https://unused.example/guide",
            final_url="https://unused.example/guide",
            fetched_at=fetched_at,
            content=b"",
            content_type="text/html",
            validators=FetchValidators(),
        )
    )

    result = GuideImportService(fetcher=fetcher).import_text(
        source_type="XIAOHONGSHU_SHARED_TEXT",
        title="广州塔小红书分享",
        content="广州塔地址是阅江西路222号，门票约150元，建议提前购票。",
        observed_at=fetched_at,
    )

    assert fetcher.source is None
    assert result.source_type == "XIAOHONGSHU_SHARED_TEXT"
    assert result.source_url.startswith("https://user-content.trippilot.invalid/")
    assert result.final_url == result.source_url
    assert result.source_host == "小红书分享文本"
    assert {fact.category for fact in result.facts} >= {
        "LOCATION",
        "COST",
        "RESERVATION",
    }

def test_imports_a_registered_official_source_as_reviewed_evidence() -> None:
    fetched_at = datetime(2026, 7, 26, 8, 0, tzinfo=UTC)
    url = "https://museum.example/visit"
    final_url = "https://museum.example/visit/current"
    fetcher = StubFetcher(
        ResourceFetched(
            status="FETCHED",
            requested_url=url,
            final_url=final_url,
            fetched_at=fetched_at,
            content=(
                "<html><title>参观须知</title><article>"
                "广州博物馆开放时间：09:00-17:00，需提前预约。"
                "</article></html>"
            ).encode(),
            content_type="text/html; charset=utf-8",
            validators=FetchValidators(),
        )
    )

    result = asyncio.run(
        GuideImportService(fetcher=fetcher).import_registered_source(
            source_url=url,
            source_name="广州博物馆",
            source_type="OFFICIAL_ATTRACTION",
            city="广州",
        )
    )

    assert result.source_type == "OFFICIAL_ATTRACTION"
    assert result.normalized_document is not None
    assert result.final_url == final_url
    assert result.normalized_document.source_url == url
    assert result.normalized_document.metadata["finalUrl"] == final_url
    assert result.normalized_document.source_reviewed is True
    assert result.normalized_document.reliability_level == "OFFICIAL_ATTRACTION"
    assert result.trusted_facts
    assert all(fact.source_reviewed for fact in result.trusted_facts)
    assert all(
        fact.normalized_value["poiName"] == "广州博物馆"
        for fact in result.trusted_facts
    )


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
