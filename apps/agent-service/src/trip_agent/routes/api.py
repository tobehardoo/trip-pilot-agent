"""Protected internal HTTP API for route facts and mode recommendation."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from math import ceil
from typing import Annotated, Literal, NoReturn

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from trip_agent.internal_security import require_internal_token
from trip_agent.providers._amap_route import AmapRouteProvider
from trip_agent.providers._amap_transit import AmapTransitProvider
from trip_agent.providers._demo_route import DemoRouteProvider
from trip_agent.providers.errors import ProviderErrorCategory, ProviderExecutionMode
from trip_agent.providers.map import Coordinates, ProviderFailure, ProviderSuccess
from trip_agent.providers.redis_cache import RedisJsonCache
from trip_agent.providers.retry import RetryingRouteProvider
from trip_agent.providers.route import RoutePlan, RouteRequest
from trip_agent.routes.service import RouteRecommendation, RouteService, RouteServiceFailure
from trip_agent.worker.runtime import WorkerSettings

router = APIRouter(prefix="/internal/v1/routes", tags=["routes"])


class InternalRouteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    origin: Coordinates
    destination: Coordinates
    mode: Literal["WALKING", "TRANSIT", "DRIVING"]
    departureAt: datetime
    originPoiId: str | None = Field(default=None, min_length=1, max_length=100)
    destinationPoiId: str | None = Field(default=None, min_length=1, max_length=100)
    city: str | None = Field(default=None, min_length=1, max_length=120)

    @field_validator("departureAt")
    @classmethod
    def require_aware_departure(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("departureAt must include a timezone offset")
        return value

    @model_validator(mode="after")
    def require_city_for_transit(self):
        if self.mode == "TRANSIT" and self.city is None:
            raise ValueError("TRANSIT route requests require city")
        return self

    def to_provider_request(self) -> RouteRequest:
        return RouteRequest(
            origin=self.origin,
            destination=self.destination,
            mode=self.mode,
            departure_at=self.departureAt,
            origin_poi_id=self.originPoiId,
            destination_poi_id=self.destinationPoiId,
            city=self.city,
        )


class InternalRecommendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    origin: Coordinates
    destination: Coordinates
    departureAt: datetime
    originPoiId: str | None = Field(default=None, min_length=1, max_length=100)
    destinationPoiId: str | None = Field(default=None, min_length=1, max_length=100)
    city: str | None = Field(default=None, min_length=1, max_length=120)
    mobilityLevel: Literal["STANDARD", "REDUCED", "STEP_FREE"] = "STANDARD"

    @field_validator("departureAt")
    @classmethod
    def require_aware_departure(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("departureAt must include a timezone offset")
        return value

    def to_provider_request(self) -> RouteRequest:
        return RouteRequest(
            origin=self.origin,
            destination=self.destination,
            mode="WALKING",
            departure_at=self.departureAt,
            origin_poi_id=self.originPoiId,
            destination_poi_id=self.destinationPoiId,
            city=self.city,
        )


class RouteFactsResponse(BaseModel):
    mode: Literal["WALKING", "TRANSIT", "DRIVING"]
    distanceMeters: int
    durationSeconds: int
    polyline: list[Coordinates]
    estimatedCost: float | None
    walkingDistanceMeters: int | None
    transferCount: int | None
    provider: str
    estimated: bool
    cached: bool
    fetchedAt: datetime


class RouteRecommendationResponse(BaseModel):
    selectedMode: Literal["WALKING", "TRANSIT", "DRIVING"]
    reason: str
    providerCallsUsed: int = Field(ge=1, le=3)
    budgetDegraded: bool
    route: RouteFactsResponse


@dataclass(frozen=True, slots=True)
class RouteApiRuntime:
    service: RouteService
    client: httpx.AsyncClient | None = None
    cache: RedisJsonCache | None = None


def create_route_runtime(settings: WorkerSettings | None = None) -> RouteApiRuntime:
    resolved = settings or WorkerSettings()
    if resolved.resolved_provider_mode == ProviderExecutionMode.DEMO_ONLY:
        demo = DemoRouteProvider()
        return RouteApiRuntime(service=RouteService(demo, demo))
    key = resolved.amap_web_service_key
    if key is None:
        raise ValueError("AMap key is required in real provider mode")
    client = httpx.AsyncClient(timeout=resolved.amap_timeout_seconds)
    cache = RedisJsonCache.from_url(
        resolved.redis_connection_url(),
        socket_connect_timeout=resolved.redis_timeout_seconds,
        socket_timeout=resolved.redis_timeout_seconds,
    )
    # The recommendation contract budgets actual upstream calls, not logical
    # provider invocations.  It may probe WALKING, TRANSIT and DRIVING once
    # each, so retries must be disabled at this HTTP boundary to keep the
    # advertised hard cap of three AMap requests.
    retry_policy = replace(resolved.provider_retry_policy(), max_attempts=1)
    road = RetryingRouteProvider(
        AmapRouteProvider(
            api_key=key.get_secret_value(),
            http_client=client,
            cache=cache,
            cache_ttl_seconds=resolved.route_cache_ttl_seconds,
        ),
        retry_policy,
    )
    transit = RetryingRouteProvider(
        AmapTransitProvider(
            api_key=key.get_secret_value(),
            http_client=client,
            cache=cache,
            cache_ttl_seconds=resolved.route_cache_ttl_seconds,
        ),
        retry_policy,
    )
    return RouteApiRuntime(service=RouteService(road, transit), client=client, cache=cache)


async def close_route_runtime(runtime: RouteApiRuntime) -> None:
    if runtime.cache is not None:
        await runtime.cache.aclose()
    if runtime.client is not None:
        await runtime.client.aclose()


def get_route_service(request: Request) -> RouteService:
    runtime: RouteApiRuntime | None = getattr(request.app.state, "route_runtime", None)
    if runtime is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "route runtime is not initialized",
        )
    return runtime.service


def _facts(result: ProviderSuccess[RoutePlan]) -> RouteFactsResponse:
    plan = result.data
    return RouteFactsResponse(
        mode=plan.mode,
        distanceMeters=plan.distance_meters,
        durationSeconds=plan.duration_seconds,
        polyline=list(plan.polyline),
        estimatedCost=plan.estimated_cost,
        walkingDistanceMeters=plan.walking_distance_meters,
        transferCount=plan.transfer_count,
        provider=result.provider,
        estimated=result.estimated,
        cached=result.cached,
        fetchedAt=result.fetched_at,
    )


def _raise_failure(error: RouteServiceFailure, response: Response) -> NoReturn:
    failure: ProviderFailure = error.failure
    status_code = {
        ProviderErrorCategory.RATE_LIMITED: status.HTTP_429_TOO_MANY_REQUESTS,
        ProviderErrorCategory.TIMEOUT: status.HTTP_504_GATEWAY_TIMEOUT,
        ProviderErrorCategory.INVALID_REQUEST: status.HTTP_422_UNPROCESSABLE_ENTITY,
        ProviderErrorCategory.UNSUPPORTED_MODE: status.HTTP_422_UNPROCESSABLE_ENTITY,
        ProviderErrorCategory.NO_RESULT: status.HTTP_404_NOT_FOUND,
    }.get(failure.category, status.HTTP_502_BAD_GATEWAY)
    if failure.retry_after_seconds is not None:
        response.headers["Retry-After"] = str(max(1, ceil(failure.retry_after_seconds)))
    code = f"ROUTE_{failure.category.value}"
    raise HTTPException(
        status_code,
        {"code": code, "retryable": failure.retryable},
        headers=dict(response.headers),
    )


@router.post("", response_model=RouteFactsResponse)
async def route_facts(
    body: InternalRouteRequest,
    response: Response,
    service: Annotated[RouteService, Depends(get_route_service)],
    x_internal_token: Annotated[str | None, Header()] = None,
) -> RouteFactsResponse:
    require_internal_token(x_internal_token)
    try:
        return _facts(await service.route(body.to_provider_request()))
    except RouteServiceFailure as error:
        _raise_failure(error, response)


@router.post("/recommend", response_model=RouteRecommendationResponse)
async def recommend_route(
    body: InternalRecommendRequest,
    response: Response,
    service: Annotated[RouteService, Depends(get_route_service)],
    x_internal_token: Annotated[str | None, Header()] = None,
) -> RouteRecommendationResponse:
    require_internal_token(x_internal_token)
    try:
        recommendation: RouteRecommendation = await service.recommend(
            body.to_provider_request(),
            mobility_reduced=body.mobilityLevel != "STANDARD",
        )
    except RouteServiceFailure as error:
        _raise_failure(error, response)
    return RouteRecommendationResponse(
        selectedMode=recommendation.selected_route.data.mode,
        reason=recommendation.reason.value,
        providerCallsUsed=recommendation.provider_calls_used,
        budgetDegraded=recommendation.budget_degraded,
        route=_facts(recommendation.selected_route),
    )
