"""QWeather-backed current, forecast, and recent historical weather facts."""

import asyncio
import logging
from collections.abc import Awaitable
from datetime import date, datetime, timedelta
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import httpx
from pydantic import BaseModel, ConfigDict, Field

from trip_agent.acquisition.security import SourceSecurityError, validate_source_url
from trip_agent.guide_intelligence.models import ExtractedGuide, TravelFact

logger = logging.getLogger(__name__)
_QWEATHER_ATTRIBUTION_URL = "https://www.qweather.com"


class _ResponseModel(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


class _Location(_ResponseModel):
    location_id: str = Field(alias="id")
    name: str


class _LocationResponse(_ResponseModel):
    code: str
    location: tuple[_Location, ...] = ()


class _Now(_ResponseModel):
    obs_time: datetime = Field(alias="obsTime")
    text: str
    temp: str
    humidity: str = ""
    wind_direction: str = Field(default="", alias="windDir")
    wind_scale: str = Field(default="", alias="windScale")


class _NowResponse(_ResponseModel):
    code: str
    fx_link: object | None = Field(default=None, alias="fxLink")
    now: _Now | None = None


class _ForecastDay(_ResponseModel):
    forecast_date: date = Field(alias="fxDate")
    text_day: str = Field(alias="textDay")
    text_night: str = Field(alias="textNight")
    temperature_max: str = Field(alias="tempMax")
    temperature_min: str = Field(alias="tempMin")
    wind_direction: str = Field(default="", alias="windDirDay")
    wind_scale: str = Field(default="", alias="windScaleDay")


class _ForecastResponse(_ResponseModel):
    code: str
    fx_link: object | None = Field(default=None, alias="fxLink")
    daily: tuple[_ForecastDay, ...] = ()


class _HistoricalDaily(_ResponseModel):
    observed_date: date = Field(alias="date")
    temperature_max: str = Field(alias="tempMax")
    temperature_min: str = Field(alias="tempMin")
    humidity: str = ""
    precipitation: str = Field(default="", alias="precip")


class _HistoricalHour(_ResponseModel):
    text: str
    wind_direction: str = Field(default="", alias="windDir")
    wind_scale: str = Field(default="", alias="windScale")


class _HistoricalResponse(_ResponseModel):
    code: str
    weather_daily: _HistoricalDaily | None = Field(default=None, alias="weatherDaily")
    weather_hourly: tuple[_HistoricalHour, ...] = Field(default=(), alias="weatherHourly")


class QWeatherWeatherProvider:
    """Maps QWeather data to traceable itinerary weather facts."""

    default_api_host = "https://devapi.qweather.com"
    _shanghai = ZoneInfo("Asia/Shanghai")

    def __init__(
        self,
        *,
        api_key: str,
        http_client: httpx.AsyncClient,
        api_host: str = default_api_host,
    ) -> None:
        if not api_key.strip():
            raise ValueError("QWeather API key cannot be empty")
        self._api_key = api_key.strip()
        self._http_client = http_client
        self._api_host = _normalize_api_host(api_host)

    async def collect(
        self,
        *,
        city: str,
        start_date: date,
        end_date: date,
        checked_at: datetime,
        location_query: str | None = None,
    ) -> ExtractedGuide:
        if end_date < start_date:
            raise ValueError("QWeather date range is invalid")
        if checked_at.tzinfo is None or checked_at.utcoffset() is None:
            raise ValueError("checked_at must be timezone-aware")
        location = await self._location(location_query or city)
        current_date = checked_at.astimezone(self._shanghai).date()
        now, forecast, source_url = await self._current_and_forecast(location.location_id)
        facts: list[TravelFact] = []
        statements: list[str] = []
        unavailable_historical_dates: list[date] = []

        historical_dates = _historical_dates(start_date, end_date, current_date)
        historical_results = await asyncio.gather(*(
            self._historical_or_unavailable(location.location_id, historical_date)
            for historical_date in historical_dates
        ))
        for historical_date, (historical, error_message) in zip(
            historical_dates,
            historical_results,
            strict=True,
        ):
            if historical is None:
                unavailable_historical_dates.append(historical_date)
                logger.warning(
                    "qweather_historical_day_unavailable city=%s date=%s reason=%s",
                    city,
                    historical_date.isoformat(),
                    error_message,
                )
                continue
            if historical.weather_daily is None:
                continue
            daily = historical.weather_daily
            hourly = (
                historical.weather_hourly[len(historical.weather_hourly) // 2]
                if historical.weather_hourly
                else None
            )
            condition = hourly.text if hourly is not None else "天气实况"
            wind = _wind(hourly.wind_direction, hourly.wind_scale) if hourly is not None else ""
            statement = (
                f"{daily.observed_date.isoformat()} {location.name}历史天气：{condition}，"
                f"最高{daily.temperature_max}℃，最低{daily.temperature_min}℃，"
                f"湿度{daily.humidity or '未知'}%"
                f"{f'，{wind}' if wind else ''}"
                f"{f'，降水{daily.precipitation}mm' if daily.precipitation else ''}。"
            )
            statements.append(statement)
            facts.append(
                _weather_fact(
                    statement,
                    checked_at,
                    daily.observed_date,
                    confidence=0.94,
                )
            )

        statements.extend(
            f"{missing_date.isoformat()} 历史天气暂不可用。"
            for missing_date in unavailable_historical_dates
        )

        if now is not None:
            observed_date = now.obs_time.astimezone(self._shanghai).date()
            wind = _wind(now.wind_direction, now.wind_scale)
            statement = (
                f"{location.name}当前天气：{now.text}，{now.temp}℃，"
                f"湿度{now.humidity or '未知'}%"
                f"{f'，{wind}' if wind else ''}；"
                f"和风发布时间 {now.obs_time.isoformat()}。"
            )
            statements.append(statement)
            facts.append(
                _weather_fact(
                    statement,
                    checked_at,
                    observed_date,
                    confidence=0.92,
                    hours=6,
                )
            )

        for forecast_day in forecast:
            if not start_date <= forecast_day.forecast_date <= end_date:
                continue
            wind = _wind(forecast_day.wind_direction, forecast_day.wind_scale)
            statement = (
                f"{forecast_day.forecast_date.isoformat()} {location.name}天气预报："
                f"白天{forecast_day.text_day} {forecast_day.temperature_max}℃，"
                f"夜间{forecast_day.text_night} {forecast_day.temperature_min}℃"
                f"{f'，{wind}' if wind else ''}。"
            )
            statements.append(statement)
            facts.append(
                _weather_fact(
                    statement,
                    checked_at,
                    forecast_day.forecast_date,
                    confidence=0.9,
                )
            )

        if not facts:
            raise ValueError("QWeather returned no usable weather facts")
        return ExtractedGuide(
            title=f"{location.name}城市实时情报",
            content="\n".join(statements),
            facts=tuple(facts),
            source_url=source_url,
        )

    async def _location(self, city: str) -> _Location:
        response = _LocationResponse.model_validate(await self._get("/geo/v2/city/lookup", {
            "location": city.strip(), "range": "cn", "number": "1", "lang": "zh",
        }))
        _require_success(response.code)
        if not response.location:
            raise ValueError(f"QWeather did not recognize city: {city}")
        return response.location[0]

    async def _current_and_forecast(
        self,
        location_id: str,
    ) -> tuple[_Now | None, tuple[_ForecastDay, ...], str]:
        now_payload, forecast_payload = await _gather(
            self._get("/v7/weather/now", {"location": location_id, "lang": "zh"}),
            # 15-day forecast: covers trips up to ~2 weeks out.  The 7d endpoint
            # only reaches trips within a week, which silently dropped weather
            # for itineraries further out (e.g. 7+ days ahead).
            self._get("/v7/weather/15d", {"location": location_id, "lang": "zh"}),
        )
        now_response = _NowResponse.model_validate(now_payload)
        forecast_response = _ForecastResponse.model_validate(forecast_payload)
        _require_success(now_response.code)
        _require_success(forecast_response.code)
        return (
            now_response.now,
            forecast_response.daily,
            _safe_qweather_fx_link(now_response.fx_link, forecast_response.fx_link),
        )

    async def _historical(self, location_id: str, requested_date: date) -> _HistoricalResponse:
        payload = await self._get(
            "/v7/historical/weather",
            {
                "location": location_id,
                "date": requested_date.strftime("%Y%m%d"),
                "lang": "zh",
                "unit": "m",
            },
        )
        response = _HistoricalResponse.model_validate(payload)
        _require_success(response.code)
        return response

    async def _historical_or_unavailable(
        self,
        location_id: str,
        requested_date: date,
    ) -> tuple[_HistoricalResponse | None, str | None]:
        try:
            return await self._historical(location_id, requested_date), None
        except (RuntimeError, ValueError) as error:
            return None, str(error)

    async def _get(self, path: str, params: dict[str, str]) -> object:
        try:
            response = await self._http_client.get(
                f"{self._api_host}{path}",
                params=params,
                headers={"X-QW-Api-Key": self._api_key},
            )
            response.raise_for_status()
            return response.json()
        except httpx.TimeoutException as error:
            raise RuntimeError("QWeather request timed out") from error
        except httpx.HTTPStatusError as error:
            raise RuntimeError(
                f"QWeather request failed with status {error.response.status_code}"
            ) from error
        except httpx.HTTPError as error:
            raise RuntimeError("QWeather request failed") from error


async def _gather[T, U](
    first: Awaitable[T],
    second: Awaitable[U],
) -> tuple[T, U]:
    first_result, second_result = await asyncio.gather(first, second)
    return first_result, second_result


def _normalize_api_host(api_host: str) -> str:
    candidate = api_host.strip().rstrip("/")
    if not candidate:
        raise ValueError("QWeather API host cannot be empty")
    if "://" not in candidate:
        candidate = f"https://{candidate}"
    parsed = urlparse(candidate)
    if parsed.scheme != "https" or not parsed.netloc or parsed.path not in ("", "/"):
        raise ValueError("QWeather API host must be an HTTPS domain without a path")
    return candidate


def _safe_qweather_fx_link(*candidates: object | None) -> str:
    for candidate in candidates:
        if not isinstance(candidate, str):
            continue
        try:
            return validate_source_url(candidate, allowed_domains=("qweather.com",))
        except (SourceSecurityError, ValueError):
            continue
    return _QWEATHER_ATTRIBUTION_URL


def _historical_dates(start_date: date, end_date: date, current_date: date) -> tuple[date, ...]:
    first = max(start_date, current_date - timedelta(days=10))
    last = min(end_date, current_date - timedelta(days=1))
    if last < first:
        return ()
    return tuple(first + timedelta(days=offset) for offset in range((last - first).days + 1))


def _wind(direction: str, scale: str) -> str:
    return f"{direction}{scale}级" if direction and scale else direction or scale


def _weather_fact(
    statement: str,
    checked_at: datetime,
    effective_date: date,
    *,
    confidence: float,
    hours: int = 24,
) -> TravelFact:
    return TravelFact(
        category="WEATHER",
        statement=statement,
        evidence=statement,
        confidence=confidence,
        observed_at=checked_at,
        expires_at=checked_at + timedelta(hours=hours),
        effective_date=effective_date,
    )


def _require_success(code: str) -> None:
    if code != "200":
        raise ValueError(f"QWeather rejected weather request ({code})")
