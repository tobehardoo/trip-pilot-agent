"""Typed map provider contracts shared by planning and infrastructure adapters."""

import hashlib
import json
import logging
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from time import perf_counter
from typing import Annotated, Literal, Protocol

import httpx
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

logger = logging.getLogger(__name__)


class _AmapCredentialLogFilter(logging.Filter):
    """Redact AMap query credentials before HTTPX records reach handlers."""

    redacts_amap_credentials = True
    _key_pattern = re.compile(r"([?&]key=)[^&\s\"]+", re.IGNORECASE)

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self._redact(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(self._redact(value) for value in record.args)
        elif isinstance(record.args, dict):
            record.args = {key: self._redact(value) for key, value in record.args.items()}
        return True

    @classmethod
    def _redact(cls, value: object) -> object:
        if isinstance(value, httpx.URL) and "key" in value.params:
            return value.copy_set_param("key", "REDACTED")
        if isinstance(value, str):
            return cls._key_pattern.sub(r"\1REDACTED", value)
        return value


def _install_httpx_credential_filter() -> None:
    httpx_logger = logging.getLogger("httpx")
    already_installed = any(
        getattr(item, "redacts_amap_credentials", False) for item in httpx_logger.filters
    )
    if not already_installed:
        httpx_logger.addFilter(_AmapCredentialLogFilter())


_install_httpx_credential_filter()

type MapProviderName = Literal["AMAP", "DEMO"]
type ProviderErrorCode = Literal[
    "POI_NOT_FOUND",
    "PROVIDER_AUTH_FAILED",
    "PROVIDER_RATE_LIMITED",
    "PROVIDER_QUOTA_EXHAUSTED",
    "PROVIDER_REQUEST_INVALID",
    "PROVIDER_TIMEOUT",
    "PROVIDER_UNAVAILABLE",
    "PROVIDER_SCHEMA_CHANGED",
    "PROVIDER_ERROR",
]
type NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
type CityText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)
]
type KeywordText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)
]

class ProviderModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Coordinates(ProviderModel):
    longitude: float = Field(ge=-180, le=180)
    latitude: float = Field(ge=-90, le=90)


class Poi(ProviderModel):
    provider_id: NonEmptyText
    name: NonEmptyText
    coordinates: Coordinates
    type_name: str
    type_code: str
    province: str
    city: str
    district: str
    address: str


class PoiSearchRequest(ProviderModel):
    city: CityText
    keyword: KeywordText
    limit: int = Field(default=10, strict=True, ge=1, le=25)


class ProviderSuccess[DataT](ProviderModel):
    data: DataT
    provider: MapProviderName
    latency_ms: int = Field(ge=0)
    cached: bool
    fetched_at: datetime
    estimated: bool


class ProviderFailure(ProviderModel):
    provider: MapProviderName
    error_code: ProviderErrorCode
    error_message: NonEmptyText
    retryable: bool
    latency_ms: int = Field(ge=0)
    cached: bool = False
    fetched_at: datetime
    estimated: bool = False


type PoiSearchResult = ProviderSuccess[tuple[Poi, ...]] | ProviderFailure


class MapProvider(Protocol):
    async def search_pois(self, request: PoiSearchRequest) -> PoiSearchResult: ...


class JsonCache(Protocol):
    async def get(self, key: str) -> str | None: ...

    async def set(self, key: str, value: str, *, ttl_seconds: int) -> None: ...


class _AmapPoi(BaseModel):
    model_config = ConfigDict(extra="ignore")

    provider_id: str = Field(alias="id")
    name: str
    location: str
    type_name: str = Field(alias="type")
    type_code: str = Field(alias="typecode")
    province: str = Field(alias="pname")
    city: str = Field(alias="cityname")
    district: str = Field(alias="adname")
    address: str


class _AmapTextResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: str
    info: str
    infocode: str
    pois: tuple[_AmapPoi, ...] = ()

    @model_validator(mode="before")
    @classmethod
    def require_pois_for_success(cls, value: object) -> object:
        if isinstance(value, Mapping) and value.get("status") == "1" and "pois" not in value:
            raise ValueError("successful AMap response must include pois")
        return value


class _CachedPoiSearch(ProviderModel):
    data: tuple[Poi, ...]
    fetched_at: datetime


class AmapMapProvider:
    """AMap v5 POI text-search adapter with an optional JSON cache."""

    endpoint = "https://restapi.amap.com/v5/place/text"
    _auth_error_codes = frozenset(
        {
            "10001",
            "10002",
            "10005",
            "10006",
            "10007",
            "10008",
            "10009",
            "10011",
            "10012",
            "10013",
            "10026",
            "10041",
            "20011",
        }
    )
    _rate_error_codes = frozenset(
        {"10004", "10014", "10015", "10016", "10019", "10020", "10021", "10029"}
    )
    _quota_error_codes = frozenset(
        {"10003", "10010", "10044", "10045", "40000", "40001", "40002", "40003"}
    )
    _unavailable_error_codes = frozenset({"10017"})
    _invalid_request_codes = frozenset({"20000", "20001", "20002", "20012"})

    def __init__(
        self,
        *,
        api_key: str,
        http_client: httpx.AsyncClient,
        cache: JsonCache | None = None,
        cache_ttl_seconds: int = 86_400,
    ) -> None:
        if not api_key.strip():
            raise ValueError("AMap API key cannot be empty")
        if cache_ttl_seconds <= 0:
            raise ValueError("cache TTL must be positive")

        self._api_key = api_key.strip()
        self._http_client = http_client
        self._cache = cache
        self._cache_ttl_seconds = cache_ttl_seconds

    async def search_pois(self, request: PoiSearchRequest) -> PoiSearchResult:
        started_at = perf_counter()
        cache_key = self._cache_key(request)

        cached = await self._read_cache(cache_key)
        if cached is not None:
            return ProviderSuccess(
                data=cached.data,
                provider="AMAP",
                latency_ms=self._elapsed_ms(started_at),
                cached=True,
                fetched_at=cached.fetched_at,
                estimated=False,
            )

        try:
            response = await self._http_client.get(
                self.endpoint,
                params={
                    "key": self._api_key,
                    "keywords": request.keyword,
                    "region": request.city,
                    "city_limit": "true",
                    "page_size": str(request.limit),
                    "page_num": "1",
                    "output": "json",
                },
            )
        except httpx.TimeoutException:
            return self._failure(
                "PROVIDER_TIMEOUT",
                "AMap request timed out",
                retryable=True,
                started_at=started_at,
            )
        except httpx.RequestError:
            return self._failure(
                "PROVIDER_UNAVAILABLE",
                "AMap is temporarily unavailable",
                retryable=True,
                started_at=started_at,
            )

        if response.status_code >= 400:
            return self._http_failure(response.status_code, started_at)

        try:
            payload = _AmapTextResponse.model_validate(response.json())
        except (ValidationError, ValueError, TypeError):
            return self._failure(
                "PROVIDER_SCHEMA_CHANGED",
                "AMap returned an unexpected response",
                retryable=False,
                started_at=started_at,
            )

        if payload.status != "1" or payload.infocode != "10000":
            return self._business_failure(payload.infocode, started_at)

        fetched_at = datetime.now(UTC)
        try:
            pois = tuple(self._to_poi(item) for item in payload.pois)
        except (ValidationError, ValueError, TypeError):
            return self._failure(
                "PROVIDER_SCHEMA_CHANGED",
                "AMap returned an unexpected POI structure",
                retryable=False,
                started_at=started_at,
            )

        if not pois:
            return self._failure(
                "POI_NOT_FOUND",
                "No matching POIs were found",
                retryable=False,
                started_at=started_at,
            )

        result = ProviderSuccess(
            data=pois,
            provider="AMAP",
            latency_ms=self._elapsed_ms(started_at),
            cached=False,
            fetched_at=fetched_at,
            estimated=False,
        )
        await self._write_cache(
            cache_key,
            _CachedPoiSearch(data=pois, fetched_at=fetched_at),
        )
        return result

    async def _read_cache(self, cache_key: str) -> _CachedPoiSearch | None:
        if self._cache is None:
            return None
        try:
            cached_value = await self._cache.get(cache_key)
            if cached_value is None:
                return None
            return _CachedPoiSearch.model_validate_json(cached_value)
        except Exception:
            logger.warning("Ignoring unreadable POI cache entry", exc_info=True)
            return None

    async def _write_cache(self, cache_key: str, value: _CachedPoiSearch) -> None:
        if self._cache is None:
            return
        try:
            await self._cache.set(
                cache_key,
                value.model_dump_json(),
                ttl_seconds=self._cache_ttl_seconds,
            )
        except Exception:
            logger.warning("POI cache write failed", exc_info=True)

    def _http_failure(self, status_code: int, started_at: float) -> ProviderFailure:
        if status_code == 408:
            return self._failure(
                "PROVIDER_TIMEOUT",
                "AMap request timed out",
                retryable=True,
                started_at=started_at,
            )
        if status_code in {401, 403}:
            return self._failure(
                "PROVIDER_AUTH_FAILED",
                "AMap authentication failed",
                retryable=False,
                started_at=started_at,
            )
        if status_code == 429:
            return self._failure(
                "PROVIDER_RATE_LIMITED",
                "AMap rate limit was reached",
                retryable=True,
                started_at=started_at,
            )
        if status_code >= 500:
            return self._failure(
                "PROVIDER_UNAVAILABLE",
                "AMap is temporarily unavailable",
                retryable=True,
                started_at=started_at,
            )
        return self._failure(
            "PROVIDER_ERROR",
            "AMap request failed",
            retryable=False,
            started_at=started_at,
        )

    def _business_failure(self, infocode: str, started_at: float) -> ProviderFailure:
        if infocode in self._auth_error_codes:
            code: ProviderErrorCode = "PROVIDER_AUTH_FAILED"
            message = "AMap authentication failed"
            retryable = False
        elif infocode in self._rate_error_codes:
            code = "PROVIDER_RATE_LIMITED"
            message = "AMap rate limit was reached"
            retryable = True
        elif infocode in self._quota_error_codes:
            code = "PROVIDER_QUOTA_EXHAUSTED"
            message = "AMap quota was exhausted"
            retryable = False
        elif infocode in self._unavailable_error_codes or infocode.startswith("3"):
            code = "PROVIDER_UNAVAILABLE"
            message = "AMap is temporarily unavailable"
            retryable = True
        elif infocode in self._invalid_request_codes:
            code = "PROVIDER_REQUEST_INVALID"
            message = "AMap rejected the request parameters"
            retryable = False
        else:
            code = "PROVIDER_ERROR"
            message = "AMap returned an error"
            retryable = False
        return self._failure(code, message, retryable=retryable, started_at=started_at)

    @staticmethod
    def _failure(
        error_code: ProviderErrorCode,
        error_message: str,
        *,
        retryable: bool,
        started_at: float,
    ) -> ProviderFailure:
        return ProviderFailure(
            provider="AMAP",
            error_code=error_code,
            error_message=error_message,
            retryable=retryable,
            latency_ms=AmapMapProvider._elapsed_ms(started_at),
            fetched_at=datetime.now(UTC),
        )

    @staticmethod
    def _cache_key(request: PoiSearchRequest) -> str:
        source = json.dumps(
            [request.city, request.keyword, request.limit],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
        return f"map:poi:v1:{hashlib.sha256(source).hexdigest()}"

    @staticmethod
    def _to_poi(item: _AmapPoi) -> Poi:
        longitude_text, latitude_text = item.location.split(",", maxsplit=1)
        return Poi(
            provider_id=item.provider_id,
            name=item.name,
            coordinates=Coordinates(
                longitude=float(longitude_text),
                latitude=float(latitude_text),
            ),
            type_name=item.type_name,
            type_code=item.type_code,
            province=item.province,
            city=item.city,
            district=item.district,
            address=item.address,
        )

    @staticmethod
    def _elapsed_ms(started_at: float) -> int:
        return max(0, int((perf_counter() - started_at) * 1000))


class DemoMapProvider:
    """Deterministic offline provider for local planning and contract tests."""

    async def search_pois(self, request: PoiSearchRequest) -> PoiSearchResult:
        started_at = perf_counter()
        source = json.dumps(
            [request.city, request.keyword],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
        provider_id = hashlib.sha256(source).hexdigest()[:16]
        poi = Poi(
            provider_id=f"demo-{provider_id}",
            name=f"{request.keyword} (demo)",
            coordinates=Coordinates(longitude=113.2644, latitude=23.1291),
            type_name="Demo POI",
            type_code="DEMO",
            province="",
            city=request.city,
            district="",
            address=f"Demo location in {request.city}",
        )
        return ProviderSuccess(
            data=(poi,),
            provider="DEMO",
            latency_ms=AmapMapProvider._elapsed_ms(started_at),
            cached=False,
            fetched_at=datetime.now(UTC),
            estimated=True,
        )
