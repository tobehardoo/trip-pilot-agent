"""AMap-backed city facts collected before a planning snapshot is frozen."""

import asyncio
from datetime import date, datetime, timedelta
from typing import Annotated

import httpx
from pydantic import BaseModel, ConfigDict, Field

from trip_agent.guide_intelligence.models import ExtractedGuide, FactCategory, TravelFact
from trip_agent.providers.map import _install_httpx_credential_filter

_install_httpx_credential_filter()


class _ResponseModel(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


class _District(_ResponseModel):
    name: str
    adcode: str
    level: str


class _DistrictResponse(_ResponseModel):
    status: str
    infocode: str
    districts: tuple[_District, ...] = ()


class _LiveWeather(_ResponseModel):
    city: str
    weather: str
    temperature: str
    humidity: str = ""
    winddirection: str = ""
    windpower: str = ""
    reporttime: str


class _WeatherCast(_ResponseModel):
    date: date
    dayweather: str
    nightweather: str
    daytemp: str
    nighttemp: str
    daywind: str = ""
    daypower: str = ""


class _Forecast(_ResponseModel):
    city: str
    reporttime: str
    casts: tuple[_WeatherCast, ...] = ()


class _WeatherResponse(_ResponseModel):
    status: str
    infocode: str
    lives: tuple[_LiveWeather, ...] = ()
    forecasts: tuple[_Forecast, ...] = ()


class _PoiBusiness(_ResponseModel):
    cost: str = ""
    opentime_today: str = ""
    opentime_week: str = ""


class _Poi(_ResponseModel):
    poi_id: str = Field(alias="id")
    name: str
    location: str
    address: str
    district: str = Field(default="", alias="adname")
    business: _PoiBusiness = _PoiBusiness()


class _PoiResponse(_ResponseModel):
    status: str
    infocode: str
    pois: tuple[_Poi, ...] = ()


CheckedAt = Annotated[datetime, Field()]


class AmapCityIntelligenceProvider:
    """Collect current weather, forecast, and high-value attraction metadata."""

    district_endpoint = "https://restapi.amap.com/v3/config/district"
    weather_endpoint = "https://restapi.amap.com/v3/weather/weatherInfo"
    poi_endpoint = "https://restapi.amap.com/v5/place/text"

    def __init__(self, *, api_key: str, http_client: httpx.AsyncClient) -> None:
        if not api_key.strip():
            raise ValueError("AMap API key cannot be empty")
        self._api_key = api_key.strip()
        self._http_client = http_client

    async def collect(
        self,
        *,
        city: str,
        start_date: date,
        end_date: date,
        checked_at: CheckedAt,
    ) -> ExtractedGuide:
        normalized_city = city.strip()
        if not normalized_city:
            raise ValueError("city cannot be empty")
        if end_date < start_date:
            raise ValueError("city intelligence date range is invalid")
        if checked_at.tzinfo is None or checked_at.utcoffset() is None:
            raise ValueError("checked_at must be timezone-aware")

        district = await self._district(normalized_city)
        live, forecast, pois = await asyncio.gather(
            self._weather(district.adcode, "base"),
            self._weather(district.adcode, "all"),
            self._pois(normalized_city),
        )
        statements: list[str] = []
        facts: list[TravelFact] = []

        if live.lives:
            item = live.lives[0]
            statement = (
                f"{item.city}当前天气：{item.weather}，{item.temperature}℃，"
                f"湿度{item.humidity or '未知'}%，{item.winddirection or '未知'}风"
                f"{item.windpower or '未知'}级；高德发布时间 {item.reporttime}。"
            )
            statements.append(statement)
            facts.append(
                _fact(
                    "WEATHER",
                    statement,
                    checked_at,
                    effective_date=date.fromisoformat(item.reporttime[:10]),
                    hours=6,
                    confidence=0.92,
                )
            )

        if forecast.forecasts:
            for cast in forecast.forecasts[0].casts:
                if not start_date <= cast.date <= end_date:
                    continue
                statement = (
                    f"{cast.date.isoformat()} {district.name}天气预报："
                    f"白天{cast.dayweather} {cast.daytemp}℃，"
                    f"夜间{cast.nightweather} {cast.nighttemp}℃，"
                    f"{cast.daywind or '未知'}风{cast.daypower or '未知'}级。"
                )
                statements.append(statement)
                facts.append(
                    _fact(
                        "WEATHER",
                        statement,
                        checked_at,
                        effective_date=cast.date,
                        hours=24,
                        confidence=0.9,
                    )
                )

        for poi in pois.pois[:8]:
            base = (
                f"{poi.name}：地址{poi.district}{poi.address}；"
                f"坐标{poi.location}"
            )
            details = []
            if poi.business.cost:
                details.append(f"高德参考消费{poi.business.cost}元")
            opening = poi.business.opentime_today or poi.business.opentime_week
            if opening:
                details.append(f"营业信息{opening}")
            statement = f"{base}{';' if details else ''}{'；'.join(details)}。"
            statements.append(statement)
            facts.extend(
                (
                    _fact("ATTRACTION", statement, checked_at, days=30, confidence=0.86),
                    _fact("LOCATION", statement, checked_at, days=90, confidence=0.94),
                )
            )
            if poi.business.cost:
                facts.append(_fact("COST", statement, checked_at, days=7, confidence=0.78))
            if opening:
                facts.append(_fact("TIMING", statement, checked_at, days=1, confidence=0.8))

        if not statements:
            raise ValueError("city intelligence provider returned no usable facts")
        return ExtractedGuide(
            title=f"{district.name}城市实时情报",
            content="\n".join(statements),
            facts=tuple(facts[:100]),
        )

    async def _district(self, city: str) -> _District:
        response = await self._get(
            self.district_endpoint,
            params={
                "key": self._api_key,
                "keywords": city,
                "subdistrict": "0",
                "extensions": "base",
                "output": "json",
            },
        )
        payload = _DistrictResponse.model_validate(response.json())
        _require_success(payload.status, payload.infocode)
        if not payload.districts:
            raise ValueError(f"AMap did not recognize city: {city}")
        return payload.districts[0]

    async def _weather(self, adcode: str, extensions: str) -> _WeatherResponse:
        response = await self._get(
            self.weather_endpoint,
            params={
                "key": self._api_key,
                "city": adcode,
                "extensions": extensions,
                "output": "json",
            },
        )
        payload = _WeatherResponse.model_validate(response.json())
        _require_success(payload.status, payload.infocode)
        return payload

    async def _pois(self, city: str) -> _PoiResponse:
        response = await self._get(
            self.poi_endpoint,
            params={
                "key": self._api_key,
                "types": "110000",
                "region": city,
                "city_limit": "true",
                "show_fields": "business",
                "page_size": "8",
                "page_num": "1",
                "output": "json",
            },
        )
        payload = _PoiResponse.model_validate(response.json())
        _require_success(payload.status, payload.infocode)
        return payload

    async def _get(self, url: str, *, params: dict[str, str]) -> httpx.Response:
        try:
            response = await self._http_client.get(url, params=params)
            response.raise_for_status()
            return response
        except httpx.TimeoutException as error:
            raise RuntimeError("AMap city intelligence request timed out") from error
        except httpx.HTTPError as error:
            raise RuntimeError("AMap city intelligence request failed") from error


def _require_success(status: str, infocode: str) -> None:
    if status != "1" or infocode != "10000":
        raise ValueError(f"AMap rejected city intelligence request ({infocode})")


def _fact(
    category: FactCategory,
    statement: str,
    checked_at: datetime,
    *,
    effective_date: date | None = None,
    hours: int | None = None,
    days: int | None = None,
    confidence: float,
) -> TravelFact:
    ttl = timedelta(hours=hours) if hours is not None else timedelta(days=days or 1)
    return TravelFact(
        category=category,
        statement=statement,
        evidence=statement,
        confidence=confidence,
        observed_at=checked_at,
        expires_at=checked_at + ttl,
        effective_date=effective_date,
    )
