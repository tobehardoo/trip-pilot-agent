import asyncio
from datetime import UTC, date, datetime

import httpx
import pytest

from trip_agent.guide_intelligence.qweather import QWeatherWeatherProvider


@pytest.mark.parametrize(
    "api_host",
    ["", "http://weather.example.com", "https://weather.example.com/api"],
)
def test_rejects_invalid_qweather_api_host(api_host: str) -> None:
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: None))

    with pytest.raises(ValueError, match="QWeather API host"):
        QWeatherWeatherProvider(
            api_key="test-key",
            http_client=client,
            api_host=api_host,
        )

    asyncio.run(client.aclose())


def test_rejects_an_invalid_weather_date_range_before_requesting_qweather() -> None:
    request_count = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return httpx.Response(500)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = QWeatherWeatherProvider(
        api_key="test-key",
        http_client=client,
        api_host="weather.example.com",
    )

    with pytest.raises(ValueError, match="date range"):
        asyncio.run(
            provider.collect(
                city="广州",
                start_date=date(2026, 8, 4),
                end_date=date(2026, 8, 2),
                checked_at=datetime(2026, 8, 2, tzinfo=UTC),
            )
        )

    asyncio.run(client.aclose())
    assert request_count == 0


def test_reports_qweather_timeout_without_exposing_the_api_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = QWeatherWeatherProvider(
        api_key="secret-qweather-key",
        http_client=client,
        api_host="weather.example.com",
    )

    with pytest.raises(RuntimeError, match="QWeather request timed out") as error:
        asyncio.run(
            provider.collect(
                city="广州",
                start_date=date(2026, 8, 2),
                end_date=date(2026, 8, 4),
                checked_at=datetime(2026, 8, 2, tzinfo=UTC),
            )
        )

    asyncio.run(client.aclose())
    assert "secret-qweather-key" not in str(error.value)


def test_collects_recent_history_current_weather_and_forecast() -> None:
    historical_dates: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-QW-Api-Key"] == "test-key"
        assert request.url.params.get("key") is None
        if request.url.path == "/geo/v2/city/lookup":
            assert request.url.params["location"] == "113.27,23.13"
            return httpx.Response(
                200,
                json={
                    "code": "200",
                    "location": [{"id": "101280101", "name": "广州"}],
                },
            )
        if request.url.path == "/v7/weather/now":
            return httpx.Response(200, json={"code": "200", "now": {
                "obsTime": "2026-07-30T13:00+08:00", "text": "阴", "temp": "31",
                "humidity": "73", "windDir": "东北风", "windScale": "3",
            }})
        if request.url.path == "/v7/weather/7d":
            return httpx.Response(200, json={"code": "200", "daily": [{
                "fxDate": "2026-07-31", "textDay": "多云", "textNight": "晴",
                "tempMax": "34", "tempMin": "27", "windDirDay": "东风", "windScaleDay": "3",
            }]})
        if request.url.path == "/v7/historical/weather":
            historical_dates.append(request.url.params["date"])
            raw_date = request.url.params["date"]
            return httpx.Response(
                200,
                json={
                    "code": "200",
                    "weatherDaily": {
                        "date": f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}",
                        "tempMax": "33",
                        "tempMin": "26",
                        "humidity": "80",
                        "precip": "2.1",
                    },
                    "weatherHourly": [
                        {
                            "time": "2026-07-25 12:00",
                            "text": "阵雨",
                            "windDir": "南风",
                            "windScale": "2",
                        }
                    ],
                },
            )
        raise AssertionError(f"unexpected request: {request.url}")

    checked_at = datetime(2026, 7, 30, 5, 0, tzinfo=UTC)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = QWeatherWeatherProvider(
        api_key="test-key",
        http_client=client,
        api_host="weather.test.qweatherapi.com",
    )

    result = asyncio.run(
        provider.collect(
            city="广州",
            start_date=date(2026, 7, 25),
            end_date=date(2026, 7, 31),
            checked_at=checked_at,
            location_query="113.27,23.13",
        )
    )
    asyncio.run(client.aclose())

    assert historical_dates == ["20260725", "20260726", "20260727", "20260728", "20260729"]
    effective_dates = {fact.effective_date for fact in result.facts}
    assert effective_dates >= {date(2026, 7, 25), date(2026, 7, 30), date(2026, 7, 31)}
    assert "历史天气" in result.content
    assert "当前天气" in result.content
    assert "天气预报" in result.content


def test_keeps_current_and_forecast_when_one_historical_day_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/geo/v2/city/lookup":
            return httpx.Response(
                200,
                json={"code": "200", "location": [{"id": "101280101", "name": "广州"}]},
            )
        if request.url.path == "/v7/weather/now":
            return httpx.Response(200, json={"code": "200", "now": {
                "obsTime": "2026-07-30T13:00+08:00", "text": "阴", "temp": "31",
            }})
        if request.url.path == "/v7/weather/7d":
            return httpx.Response(200, json={"code": "200", "daily": [{
                "fxDate": "2026-07-31", "textDay": "多云", "textNight": "晴",
                "tempMax": "34", "tempMin": "27",
            }]})
        if request.url.path == "/v7/historical/weather":
            raw_date = request.url.params["date"]
            if raw_date == "20260729":
                return httpx.Response(200, json={"code": "403"})
            return httpx.Response(200, json={
                "code": "200",
                "weatherDaily": {
                    "date": "2026-07-28", "tempMax": "33", "tempMin": "26",
                },
            })
        raise AssertionError(f"unexpected request: {request.url}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = QWeatherWeatherProvider(
        api_key="test-key",
        http_client=client,
        api_host="weather.test.qweatherapi.com",
    )

    result = asyncio.run(
        provider.collect(
            city="广州",
            start_date=date(2026, 7, 28),
            end_date=date(2026, 7, 31),
            checked_at=datetime(2026, 7, 30, 5, 0, tzinfo=UTC),
        )
    )
    asyncio.run(client.aclose())

    assert {fact.effective_date for fact in result.facts} >= {
        date(2026, 7, 28),
        date(2026, 7, 30),
        date(2026, 7, 31),
    }
    assert "2026-07-29 历史天气暂不可用" in result.content


def test_collects_historical_days_concurrently() -> None:
    active_historical_requests = 0
    max_active_historical_requests = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal active_historical_requests, max_active_historical_requests
        if request.url.path == "/geo/v2/city/lookup":
            return httpx.Response(
                200,
                json={"code": "200", "location": [{"id": "101280101", "name": "广州"}]},
            )
        if request.url.path == "/v7/weather/now":
            return httpx.Response(200, json={"code": "200"})
        if request.url.path == "/v7/weather/7d":
            return httpx.Response(200, json={"code": "200", "daily": []})
        if request.url.path == "/v7/historical/weather":
            active_historical_requests += 1
            max_active_historical_requests = max(
                max_active_historical_requests,
                active_historical_requests,
            )
            await asyncio.sleep(0.01)
            active_historical_requests -= 1
            raw_date = request.url.params["date"]
            return httpx.Response(200, json={
                "code": "200",
                "weatherDaily": {
                    "date": f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}",
                    "tempMax": "30",
                    "tempMin": "20",
                },
            })
        raise AssertionError(f"unexpected request: {request.url}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = QWeatherWeatherProvider(
        api_key="test-key",
        http_client=client,
        api_host="weather.test.qweatherapi.com",
    )

    asyncio.run(
        provider.collect(
            city="广州",
            start_date=date(2026, 7, 27),
            end_date=date(2026, 7, 29),
            checked_at=datetime(2026, 7, 30, 5, 0, tzinfo=UTC),
        )
    )
    asyncio.run(client.aclose())

    assert max_active_historical_requests == 3


def test_rejects_a_response_with_only_historical_failure_notices() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/geo/v2/city/lookup":
            return httpx.Response(
                200,
                json={"code": "200", "location": [{"id": "101280101", "name": "广州"}]},
            )
        if request.url.path == "/v7/weather/now":
            return httpx.Response(200, json={"code": "200"})
        if request.url.path == "/v7/weather/7d":
            return httpx.Response(200, json={"code": "200", "daily": []})
        if request.url.path == "/v7/historical/weather":
            return httpx.Response(200, json={"code": "403"})
        raise AssertionError(f"unexpected request: {request.url}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = QWeatherWeatherProvider(
        api_key="test-key",
        http_client=client,
        api_host="weather.test.qweatherapi.com",
    )

    with pytest.raises(ValueError, match="no usable weather facts"):
        asyncio.run(
            provider.collect(
                city="广州",
                start_date=date(2026, 7, 29),
                end_date=date(2026, 7, 29),
                checked_at=datetime(2026, 7, 30, 5, 0, tzinfo=UTC),
            )
        )
    asyncio.run(client.aclose())
