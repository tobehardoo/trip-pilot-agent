import asyncio
from datetime import UTC, date, datetime

import httpx

from trip_agent.guide_intelligence.city_intelligence import (
    AmapCityIntelligenceProvider,
    normalize_poi_address,
)


def test_normalizes_repeated_administrative_address_segments() -> None:
    assert normalize_poi_address("西湖区", "西湖街道西湖街道西湖街道杨公堤10号") == (
        "西湖区西湖街道杨公堤10号"
    )


def test_collects_weather_and_attraction_details_as_traceable_facts() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v3/config/district":
            return httpx.Response(
                200,
                json={
                    "status": "1",
                    "infocode": "10000",
                    "districts": [{"name": "广州市", "adcode": "440100", "level": "city"}],
                },
            )
        if request.url.path == "/v3/weather/weatherInfo":
            if request.url.params["extensions"] == "base":
                return httpx.Response(
                    200,
                    json={
                        "status": "1",
                        "infocode": "10000",
                        "lives": [{
                            "city": "广州市",
                            "weather": "雷阵雨",
                            "temperature": "31",
                            "humidity": "78",
                            "winddirection": "南",
                            "windpower": "≤3",
                            "reporttime": "2026-07-26 12:00:00",
                        }],
                    },
                )
            return httpx.Response(
                200,
                json={
                    "status": "1",
                    "infocode": "10000",
                    "forecasts": [{
                        "city": "广州市",
                        "reporttime": "2026-07-26 11:00:00",
                        "casts": [{
                            "date": "2026-07-27",
                            "dayweather": "阵雨",
                            "nightweather": "多云",
                            "daytemp": "33",
                            "nighttemp": "26",
                            "daywind": "南",
                            "daypower": "≤3",
                        }],
                    }],
                },
            )
        if request.url.path == "/v5/place/text":
            return httpx.Response(
                200,
                json={
                    "status": "1",
                    "infocode": "10000",
                    "pois": [{
                        "id": "B001",
                        "name": "陈家祠",
                        "location": "113.246,23.129",
                        "address": "中山七路恩龙里34号",
                        "adname": "荔湾区",
                        "business": {
                            "cost": "10",
                            "opentime_today": "09:00-17:30",
                        },
                    }],
                },
            )
        raise AssertionError(f"unexpected request: {request.url}")

    checked_at = datetime(2026, 7, 26, 4, 30, tzinfo=UTC)
    async_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = AmapCityIntelligenceProvider(api_key="test-key", http_client=async_client)

    result = asyncio.run(
        provider.collect(
            city="广州",
            start_date=date(2026, 7, 27),
            end_date=date(2026, 7, 28),
            checked_at=checked_at,
        )
    )
    asyncio.run(async_client.aclose())

    categories = {fact.category for fact in result.facts}
    assert categories >= {"WEATHER", "ATTRACTION", "LOCATION", "COST", "TIMING"}
    weather_dates = {
        fact.effective_date for fact in result.facts if fact.category == "WEATHER"
    }
    assert weather_dates == {date(2026, 7, 26), date(2026, 7, 27)}
    assert "雷阵雨" in result.content
    assert "陈家祠" in result.content
    assert all(fact.observed_at == checked_at for fact in result.facts)
    assert all(fact.evidence in result.content for fact in result.facts)
