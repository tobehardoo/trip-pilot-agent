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

from trip_agent.infrastructure.amap.errors import (
    AUTH_CODES,
    INVALID_REQUEST_CODES,
    PERMISSION_CODES,
    QUOTA_CODES,
    RATE_CODES,
    UNAVAILABLE_CODES,
)
from trip_agent.providers.errors import (
    ProviderErrorCategory,
    ProviderFailureDetails,
    ProviderOperation,
    category_for_error_code,
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
    "ROUTE_NOT_FOUND",
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
type ProviderPoiId = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]
type PoiName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]
type PoiAddress = Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)]


class ProviderModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Coordinates(ProviderModel):
    longitude: float = Field(ge=-180, le=180)
    latitude: float = Field(ge=-90, le=90)


class Poi(ProviderModel):
    provider_id: ProviderPoiId
    name: PoiName
    coordinates: Coordinates
    type_name: str
    type_code: str
    province: str
    city: str
    district: str
    address: PoiAddress
    # Opening-hours text from AMap's business extension block
    # (``show_fields=business``).  Explicit ``None`` defaults keep legacy
    # cached POI payloads directly deserialisable.
    business_hours_today: str | None = None
    business_hours_week: str | None = None


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
    fallback_error: ProviderFailureDetails | None = Field(default=None, exclude=True)


class ProviderFailure(ProviderModel):
    provider: MapProviderName
    error_code: ProviderErrorCode
    error_message: NonEmptyText
    category: ProviderErrorCategory
    operation: ProviderOperation = ProviderOperation.PLANNING
    retryable: bool
    fallback_allowed: bool = False
    safe_provider_code: str | None = None
    retry_count: int = Field(default=0, ge=0, le=10)
    cause_type: str | None = None
    retry_exhausted: bool = False
    retry_after_seconds: float | None = Field(default=None, ge=0, le=3_600)
    latency_ms: int = Field(ge=0)
    cached: bool = False
    fetched_at: datetime
    estimated: bool = False

    @model_validator(mode="before")
    @classmethod
    def add_legacy_failure_classification(cls, value: object) -> object:
        if not isinstance(value, Mapping):
            return value
        classified = dict(value)
        classified.setdefault(
            "category",
            category_for_error_code(str(classified.get("error_code", ""))),
        )
        return classified


type PoiSearchResult = ProviderSuccess[tuple[Poi, ...]] | ProviderFailure


class MapProvider(Protocol):
    async def search_pois(self, request: PoiSearchRequest) -> PoiSearchResult: ...


class JsonCache(Protocol):
    async def get(self, key: str) -> str | None: ...

    async def set(self, key: str, value: str, *, ttl_seconds: int) -> None: ...


class _AmapPoiBusiness(BaseModel):
    """AMap v5 POI ``business`` extension (returned with show_fields=business)."""

    model_config = ConfigDict(extra="ignore")

    opentime_today: str = ""
    opentime_week: str = ""


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
    business: _AmapPoiBusiness | None = None


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
                    "show_fields": "business",
                },
            )
        except httpx.TimeoutException as exception:
            return self._failure(
                "PROVIDER_TIMEOUT",
                "AMap request timed out",
                retryable=True,
                started_at=started_at,
                cause_type=type(exception).__name__,
            )
        except httpx.RequestError as exception:
            return self._failure(
                "PROVIDER_UNAVAILABLE",
                "AMap is temporarily unavailable",
                category=ProviderErrorCategory.NETWORK_ERROR,
                retryable=True,
                started_at=started_at,
                cause_type=type(exception).__name__,
            )

        if response.status_code >= 400:
            return self._http_failure(response, started_at)

        try:
            payload = _AmapTextResponse.model_validate(response.json())
        except (ValidationError, ValueError, TypeError):
            return self._failure(
                "PROVIDER_SCHEMA_CHANGED",
                "AMap returned an unexpected response",
                retryable=True,
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
                retryable=True,
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

    def _http_failure(self, response: httpx.Response, started_at: float) -> ProviderFailure:
        status_code = response.status_code
        safe_code = f"HTTP_{status_code}"
        if status_code == 408:
            return self._failure(
                "PROVIDER_TIMEOUT",
                "AMap request timed out",
                retryable=True,
                started_at=started_at,
                safe_provider_code=safe_code,
            )
        if status_code == 401:
            return self._failure(
                "PROVIDER_AUTH_FAILED",
                "AMap authentication failed",
                retryable=False,
                started_at=started_at,
                safe_provider_code=safe_code,
            )
        if status_code == 403:
            return self._failure(
                "PROVIDER_AUTH_FAILED",
                "AMap permission was denied",
                category=ProviderErrorCategory.PERMISSION_DENIED,
                retryable=False,
                started_at=started_at,
                safe_provider_code=safe_code,
            )
        if status_code == 429:
            return self._failure(
                "PROVIDER_RATE_LIMITED",
                "AMap rate limit was reached",
                retryable=True,
                started_at=started_at,
                safe_provider_code=safe_code,
                retry_after_seconds=self._retry_after_seconds(response),
            )
        if status_code >= 500:
            return self._failure(
                "PROVIDER_UNAVAILABLE",
                "AMap is temporarily unavailable",
                retryable=True,
                started_at=started_at,
                safe_provider_code=safe_code,
            )
        return self._failure(
            "PROVIDER_ERROR",
            "AMap request failed",
            category=ProviderErrorCategory.INVALID_REQUEST,
            retryable=False,
            started_at=started_at,
            safe_provider_code=safe_code,
        )

    def _business_failure(self, infocode: str, started_at: float) -> ProviderFailure:
        if infocode in PERMISSION_CODES:
            code: ProviderErrorCode = "PROVIDER_AUTH_FAILED"
            message = "AMap permission was denied"
            category = ProviderErrorCategory.PERMISSION_DENIED
            retryable = False
        elif infocode in AUTH_CODES:
            code = "PROVIDER_AUTH_FAILED"
            message = "AMap authentication failed"
            category = ProviderErrorCategory.AUTHENTICATION_ERROR
            retryable = False
        elif infocode in RATE_CODES:
            code = "PROVIDER_RATE_LIMITED"
            message = "AMap rate limit was reached"
            category = ProviderErrorCategory.RATE_LIMITED
            retryable = True
        elif infocode in QUOTA_CODES:
            code = "PROVIDER_QUOTA_EXHAUSTED"
            message = "AMap quota was exhausted"
            category = ProviderErrorCategory.QUOTA_EXCEEDED
            retryable = False
        elif infocode in UNAVAILABLE_CODES or infocode.startswith("3"):
            code = "PROVIDER_UNAVAILABLE"
            message = "AMap is temporarily unavailable"
            category = ProviderErrorCategory.PROVIDER_UNAVAILABLE
            retryable = True
        elif infocode in INVALID_REQUEST_CODES:
            code = "PROVIDER_REQUEST_INVALID"
            message = "AMap rejected the request parameters"
            category = ProviderErrorCategory.INVALID_REQUEST
            retryable = False
        else:
            code = "PROVIDER_ERROR"
            message = "AMap returned an error"
            category = ProviderErrorCategory.PROVIDER_ADAPTER_ERROR
            retryable = False
        return self._failure(
            code,
            message,
            category=category,
            retryable=retryable,
            started_at=started_at,
            safe_provider_code=infocode,
        )

    @staticmethod
    def _failure(
        error_code: ProviderErrorCode,
        error_message: str,
        *,
        category: ProviderErrorCategory | None = None,
        retryable: bool,
        started_at: float,
        safe_provider_code: str | None = None,
        cause_type: str | None = None,
        retry_after_seconds: float | None = None,
    ) -> ProviderFailure:
        return ProviderFailure(
            provider="AMAP",
            error_code=error_code,
            error_message=error_message,
            category=category or category_for_error_code(error_code),
            operation=ProviderOperation.POI_SEARCH,
            retryable=retryable,
            safe_provider_code=safe_provider_code,
            cause_type=cause_type,
            retry_after_seconds=retry_after_seconds,
            latency_ms=AmapMapProvider._elapsed_ms(started_at),
            fetched_at=datetime.now(UTC),
        )

    @staticmethod
    def _retry_after_seconds(response: httpx.Response) -> float | None:
        value = response.headers.get("Retry-After")
        if value is None:
            return None
        try:
            return max(0, float(value))
        except ValueError:
            return None

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
        business = item.business
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
            business_hours_today=(
                business.opentime_today
                if business is not None and business.opentime_today
                else None
            ),
            business_hours_week=(
                business.opentime_week
                if business is not None and business.opentime_week
                else None
            ),
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
