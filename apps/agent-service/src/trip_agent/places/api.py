"""B13-D — protected place-search endpoint for the travel server proxy.

The browser never talks to a map provider: the Web app calls the owner
authenticated travel-server, which proxies here with the internal token.
Search results are *candidates* — they carry provider provenance and an
``estimated`` flag (Demo results are always estimated) but are never
verification evidence.

B13_FIX.1 R4: the HTTP client (REAL mode) and the provider are owned by the
FastAPI lifespan and reached through a typed dependency — never created
per-request and never leaked.  ``_provider()``/``_search_provider`` were
replaced by ``get_place_search_provider`` (FastAPI dependency) so tests use
``app.dependency_overrides`` instead of module-level mutable state.
"""

import os
from dataclasses import dataclass
from typing import Annotated
from unicodedata import normalize

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field

from trip_agent.internal_security import require_internal_token
from trip_agent.planning.poi_quality import place_search_selectable
from trip_agent.providers.errors import ProviderErrorCategory, ProviderExecutionMode
from trip_agent.providers.map import (
    AmapMapProvider,
    DemoMapProvider,
    MapProvider,
    Poi,
    PoiSearchRequest,
    ProviderFailure,
)
from trip_agent.providers.settings import resolve_provider_mode

router = APIRouter(prefix="/internal/v1", tags=["places"])


class PlaceSearchRequest(BaseModel):
    city: str = Field(min_length=1, max_length=120)
    keyword: str = Field(min_length=1, max_length=120)
    limit: int = Field(default=10, ge=1, le=25)


class PlaceCandidateResponse(BaseModel):
    provider: str
    providerPoiId: str
    name: str
    address: str
    province: str
    city: str
    district: str
    longitude: float
    latitude: float
    estimated: bool


class PlaceSearchResponse(BaseModel):
    provider: str
    estimated: bool
    candidates: list[PlaceCandidateResponse]


@dataclass(frozen=True, slots=True)
class PlaceSearchRuntime:
    """Typed runtime state owned by the FastAPI lifespan.

    The provider is always present; the HTTP client exists only in REAL
    mode and is closed exactly once by the lifespan shutdown.  There is no
    module-level mutable provider state.
    """

    provider: MapProvider
    client: httpx.AsyncClient | None = None


def create_place_search_runtime() -> PlaceSearchRuntime:
    """Build the runtime from environment.  DEMO_ONLY never opens a client."""
    if resolve_provider_mode() == ProviderExecutionMode.DEMO_ONLY:
        return PlaceSearchRuntime(provider=DemoMapProvider())
    key = os.getenv("AMAP_WEB_SERVICE_KEY", "").strip()
    client = httpx.AsyncClient(timeout=httpx.Timeout(15.0))
    return PlaceSearchRuntime(
        provider=AmapMapProvider(api_key=key, http_client=client, cache=None),
        client=client,
    )


async def close_place_search_runtime(runtime: PlaceSearchRuntime) -> None:
    """Close the owned HTTP client exactly once; Demo runtime closes nothing."""
    if runtime.client is not None:
        await runtime.client.aclose()


def get_place_search_provider(request: Request) -> MapProvider:
    """FastAPI dependency: the lifespan-owned provider, or fail closed.

    A missing runtime is a programming/startup error, never a silent
    per-request client creation.
    """
    runtime: PlaceSearchRuntime | None = getattr(request.app.state, "place_search_runtime", None)
    if runtime is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "place search runtime is not initialized",
        )
    return runtime.provider


def _place_name_key(value: str) -> str:
    """Canonical text key used only for deterministic search presentation."""
    return "".join(
        character for character in normalize("NFKC", value).casefold() if character.isalnum()
    )


def _exact_name_first(keyword: str, candidates: tuple[Poi, ...]) -> tuple[Poi, ...]:
    """Keep provider order except that an exact name match always leads.

    Provider ranking often places a same-name metro station, gate or parking
    facility before the attraction itself.  Stable sorting by one boolean
    preserves every other provider decision while preventing that misleading
    first choice.
    """
    keyword_key = _place_name_key(keyword)
    return tuple(
        sorted(
            candidates,
            key=lambda poi: _place_name_key(poi.name) != keyword_key,
        )
    )


@router.post("/places/search", response_model=PlaceSearchResponse)
async def search_places(
    request: PlaceSearchRequest,
    provider: Annotated[MapProvider, Depends(get_place_search_provider)],
    x_internal_token: Annotated[str | None, Header()] = None,
) -> PlaceSearchResponse:
    require_internal_token(x_internal_token)
    result = await provider.search_pois(
        PoiSearchRequest(city=request.city, keyword=request.keyword, limit=request.limit)
    )
    if isinstance(result, ProviderFailure):
        if result.category == ProviderErrorCategory.NO_RESULT:
            # B14_FIX R4 (D04): "nothing found" is a legitimate business
            # outcome, not an upstream failure — surface it as an empty
            # result set so the caller can render "未找到结果" instead of
            # a 502.  No provider detail ever leaves the boundary either
            # way.
            return PlaceSearchResponse(
                provider=result.provider,
                estimated=False,
                candidates=[],
            )
        # Safe error code + category only; raw upstream detail never leaves
        # the service boundary.
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"{result.error_code} ({result.category})",
        )
    # AMap text search freely mixes schedulable places with station gates,
    # metro/bus stops, parking and geo hot-spots ("热点地名").  Selecting one
    # of those as a must-visit is a planning dead end by design (fail-closed
    # MUST_VISIT_UNAVAILABLE) — never offer them in the picker.  Demo results
    # are a single "… (demo)" placeholder kind and stay untouched.
    raw_candidates = result.data
    if result.provider == "AMAP":
        raw_candidates = tuple(
            poi for poi in raw_candidates if place_search_selectable(poi)
        )
    candidates = _exact_name_first(request.keyword, raw_candidates)
    return PlaceSearchResponse(
        provider=result.provider,
        estimated=result.estimated,
        candidates=[
            PlaceCandidateResponse(
                provider=result.provider,
                providerPoiId=poi.provider_id,
                name=poi.name,
                address=poi.address,
                province=poi.province,
                city=poi.city,
                district=poi.district,
                longitude=float(poi.coordinates.longitude),
                latitude=float(poi.coordinates.latitude),
                estimated=result.estimated,
            )
            for poi in candidates
        ],
    )
