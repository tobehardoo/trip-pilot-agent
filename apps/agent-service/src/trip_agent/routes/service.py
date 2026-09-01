"""Route facts and B19-C recommendation orchestration for internal callers."""

from __future__ import annotations

from dataclasses import dataclass

from trip_agent.planning.mode_recommendation import (
    MAX_TRANSFERS,
    MAX_TRANSIT_DURATION_RATIO,
    MAX_TRANSIT_WALKING_METERS,
    ModeRecommendationReason,
    accessible_burdens,
    decide_transit_or_road,
)
from trip_agent.planning.transit_mode import (
    RECOVERABLE_ROUTE_CATEGORIES,
    is_walkable,
    should_try_walking,
    straight_line_distance_meters,
)
from trip_agent.providers.map import ProviderFailure, ProviderSuccess
from trip_agent.providers.route import RoutePlan, RouteProvider, RouteRequest


class RouteServiceFailure(Exception):
    def __init__(self, failure: ProviderFailure) -> None:
        super().__init__(failure.error_code)
        self.failure = failure


@dataclass(frozen=True, slots=True)
class RouteRecommendation:
    selected_route: ProviderSuccess[RoutePlan]
    reason: ModeRecommendationReason
    provider_calls_used: int
    budget_degraded: bool = False


class RouteService:
    """Dispatch provider route facts and apply the canonical B19-C rules."""

    def __init__(self, road: RouteProvider, transit: RouteProvider) -> None:
        self._road = road
        self._transit = transit

    async def route(self, request: RouteRequest) -> ProviderSuccess[RoutePlan]:
        provider = self._transit if request.mode == "TRANSIT" else self._road
        result = await provider.get_route(request)
        if isinstance(result, ProviderFailure):
            raise RouteServiceFailure(result)
        return result

    async def recommend(
        self,
        request: RouteRequest,
        *,
        mobility_reduced: bool,
    ) -> RouteRecommendation:
        calls = 0
        if should_try_walking(
            straight_line_distance_meters(request.origin, request.destination)
        ):
            calls += 1
            walking = await self._road.get_route(request.model_copy(update={"mode": "WALKING"}))
            if isinstance(walking, ProviderSuccess):
                if is_walkable(walking.data.duration_seconds):
                    return RouteRecommendation(
                        selected_route=walking,
                        reason=ModeRecommendationReason.WALKABLE,
                        provider_calls_used=calls,
                    )
            elif walking.category not in RECOVERABLE_ROUTE_CATEGORIES:
                raise RouteServiceFailure(walking)

        transit_route: ProviderSuccess[RoutePlan] | None = None
        transit_failure: ProviderFailure | None = None
        if request.city is not None:
            calls += 1
            transit_result = await self._transit.get_route(
                request.model_copy(update={"mode": "TRANSIT"})
            )
            if isinstance(transit_result, ProviderSuccess):
                transit_route = transit_result
            elif transit_result.category in RECOVERABLE_ROUTE_CATEGORIES:
                transit_failure = transit_result
            else:
                raise RouteServiceFailure(transit_result)

        calls += 1
        road_result = await self._road.get_route(request.model_copy(update={"mode": "DRIVING"}))
        road_route: ProviderSuccess[RoutePlan] | None = None
        road_failure: ProviderFailure | None = None
        if isinstance(road_result, ProviderSuccess):
            road_route = road_result
        elif road_result.category in RECOVERABLE_ROUTE_CATEGORIES:
            road_failure = road_result
        else:
            raise RouteServiceFailure(road_result)

        if road_route is None and transit_route is None:
            failure = road_failure or transit_failure
            assert failure is not None
            raise RouteServiceFailure(failure)
        if transit_route is None:
            assert road_route is not None
            return RouteRecommendation(
                selected_route=road_route,
                reason=ModeRecommendationReason.TRANSIT_UNAVAILABLE,
                provider_calls_used=calls,
            )
        if road_route is None:
            return RouteRecommendation(
                selected_route=transit_route,
                reason=ModeRecommendationReason.ROAD_UNAVAILABLE,
                provider_calls_used=calls,
            )

        transfer_limit, walking_limit = accessible_burdens(
            mobility_reduced=mobility_reduced,
            max_transfers=MAX_TRANSFERS,
            max_transit_walking_meters=MAX_TRANSIT_WALKING_METERS,
        )
        choose_transit, reason = decide_transit_or_road(
            transit_route.data.duration_seconds,
            road_route.data.duration_seconds,
            transfer_count=transit_route.data.transfer_count,
            walking_distance_meters=transit_route.data.walking_distance_meters,
            max_transit_duration_ratio=MAX_TRANSIT_DURATION_RATIO,
            max_transfers=transfer_limit,
            max_transit_walking_meters=walking_limit,
        )
        return RouteRecommendation(
            selected_route=transit_route if choose_transit else road_route,
            reason=reason,
            provider_calls_used=calls,
        )
