"""AMap-based planning provider — real POI search, route queries, and constraint solving.

Extracted from ``worker/processor.py``.  This provider depends on AMap web-service
APIs for POI search and route planning, on the candidate ranker for scoring, and on
OR‑Tools for daily schedule optimisation.
"""

from datetime import datetime, time, timedelta
from itertools import combinations
from math import ceil
from typing import TYPE_CHECKING

from trip_agent.domain.planning.protocols import (
    PlanningInfeasibleError,
    PlanningProviderError,
    PlanningResult,
    ResolvedTravelAnchors,
)
from trip_agent.domain.shared import (
    AMAP_ACTIVITY_ESTIMATED_COST,
    CHINA_TIME_ZONE,
    MAX_PAIR_ATTEMPTS_PER_PLAN,
    MAX_PLANNING_CANDIDATES,
    MAX_ROUTE_CALLS_PER_PLAN,
    amap_activity,
    available_minutes,
    candidate_keywords,
    coordinate_decimal,
    matched_guide_fact_ids,
    minute_datetime,
    text_matches,
)
from trip_agent.planning.candidates import CandidateRanker
from trip_agent.planning.optimization import (
    DailyOptimizationRequest,
    DailyOptimizer,
    OptimizationConflict,
    RelaxationSuggestion,
    TimeBlock,
)
from trip_agent.providers._demo_route import DemoRouteProvider
from trip_agent.providers.map import (
    MapProvider,
    Poi,
    PoiSearchRequest,
    ProviderFailure,
    ProviderSuccess,
)
from trip_agent.providers.route import RoutePlan, RouteProvider, RouteRequest
from trip_agent.worker.contracts import (
    ActivityCoordinates,
    Itinerary,
    ItineraryDay,
    PlanningCreateCommand,
    PlanningReplanCommand,
    TransitLeg,
)

if TYPE_CHECKING:
    pass  # All runtime types are imported above.


class AmapPlanningProvider:
    """Generates a real itinerary using AMap web-service APIs.

    Uses AMap POI search for candidate discovery, AMap route planning for
    inter‑activity transit, a deterministic :class:`CandidateRanker` for
    scoring, and OR‑Tools CP‑SAT for daily scheduling.
    """

    def __init__(
        self,
        map_provider: MapProvider,
        route_provider: RouteProvider,
        route_fallback: RouteProvider | None = None,
        candidate_ranker: CandidateRanker | None = None,
        optimizer: DailyOptimizer | None = None,
    ) -> None:
        self._map_provider = map_provider
        self._route_provider = route_provider
        self._route_fallback = route_fallback or DemoRouteProvider()
        self._candidate_ranker = candidate_ranker or CandidateRanker()
        self._optimizer = optimizer or DailyOptimizer()

    # -- public API -----------------------------------------------------------

    async def plan(self, command: PlanningCreateCommand) -> PlanningResult:
        trip = command.payload.trip
        day_count = (trip.end_date - trip.start_date).days + 1
        required_pois = day_count * 2
        raw_pois = await self._collect_pois(command, required_pois)
        candidate_pool_size = min(
            MAX_PLANNING_CANDIDATES,
            max(required_pois, required_pois * 2),
        )
        guide_statements = tuple(
            f"{fact.statement} {fact.evidence}"
            for fact in command.payload.guide_evidence.facts
        )
        baseline_ranking = self._candidate_ranker.rank(
            raw_pois,
            destination=trip.destination,
            preferences=trip.constraints.preferences,
            traveler_type=trip.constraints.traveler_type,
            limit=candidate_pool_size,
            must_visit_places=trip.constraints.must_visit_places,
            avoid_places=trip.constraints.avoid_places,
        )
        guided_ranking = self._candidate_ranker.rank(
            raw_pois,
            destination=trip.destination,
            preferences=trip.constraints.preferences,
            traveler_type=trip.constraints.traveler_type,
            limit=candidate_pool_size,
            must_visit_places=trip.constraints.must_visit_places,
            avoid_places=trip.constraints.avoid_places,
            guide_statements=guide_statements,
        )
        baseline_pois = tuple(item.poi for item in baseline_ranking.selected)
        guided_pois = tuple(item.poi for item in guided_ranking.selected)
        if len(baseline_pois) < required_pois:
            raise PlanningProviderError("INSUFFICIENT_AMAP_POIS")
        unavailable_must_visits = tuple(
            place
            for place in trip.constraints.must_visit_places
            if not any(text_matches(place, poi.name) for poi in baseline_pois)
        )
        if unavailable_must_visits:
            raise PlanningInfeasibleError(
                conflicts=(
                    OptimizationConflict(
                        "MUST_VISIT_UNAVAILABLE",
                        "必去地点未能在当前地图候选中确认",
                        unavailable_must_visits,
                    ),
                ),
                relaxations=(
                    RelaxationSuggestion(
                        "REDUCE_OPTIONAL_ACTIVITIES", "移除无法确认的必去地点后重试"
                    ),
                ),
            )
        estimated_total_cost = AMAP_ACTIVITY_ESTIMATED_COST * required_pois
        budget = trip.constraints.budget_amount
        if budget is not None and estimated_total_cost > budget:
            raise PlanningInfeasibleError(
                conflicts=(
                    OptimizationConflict(
                        "BUDGET_EXCEEDED",
                        f"预计活动费用 {estimated_total_cost:.2f} 超出预算 {budget:.2f}",
                        ("budgetAmount",),
                    ),
                ),
                relaxations=(
                    RelaxationSuggestion("INCREASE_BUDGET", "提高预算上限"),
                    RelaxationSuggestion("REDUCE_OPTIONAL_ACTIVITIES", "减少可选活动"),
                ),
            )
        anchors = await self._resolve_travel_anchors(command)
        route_cache: dict[tuple[str, ...], ProviderSuccess[RoutePlan]] = {}
        route_calls = [0]
        baseline_days, baseline_selected = await self._build_feasible_days(
            command, baseline_pois, anchors, route_cache, route_calls,
        )
        days, pois = baseline_days, baseline_selected
        guide_influenced = False
        if guide_statements and guided_pois != baseline_pois:
            try:
                days, pois = await self._build_feasible_days(
                    command, guided_pois, anchors, route_cache, route_calls,
                )
                guide_influenced = tuple(poi.provider_id for poi in pois) != tuple(
                    poi.provider_id for poi in baseline_selected
                )
            except (PlanningInfeasibleError, PlanningProviderError):
                days, pois = baseline_days, baseline_selected
        unmatched_must_visits = tuple(
            place
            for place in trip.constraints.must_visit_places
            if not any(text_matches(place, poi.name) for poi in pois)
        )
        if unmatched_must_visits:
            raise PlanningInfeasibleError(
                conflicts=(
                    OptimizationConflict(
                        "MUST_VISIT_UNAVAILABLE",
                        "必去地点无法与当前时间、路线或行动能力约束同时满足",
                        unmatched_must_visits,
                    ),
                ),
                relaxations=(
                    RelaxationSuggestion(
                        "ADJUST_TRAVEL_CONTEXT",
                        "调整到返时间、行动能力或其他必去地点后重试",
                    ),
                ),
            )
        return PlanningResult(
            provider="AMAP",
            itinerary=Itinerary(
                title=f"{trip.destination} 真实地点行程",
                days=tuple(days),
                estimated_total_cost=estimated_total_cost,
            ),
            guide_fact_ids=(
                matched_guide_fact_ids(command, pois) if guide_influenced else ()
            ),
        )

    async def replan(self, command: PlanningReplanCommand) -> PlanningResult:
        from trip_agent.application.replan_service import (  # noqa: PLC0415
            LocalReplanningProvider,
        )

        return await LocalReplanningProvider(
            self._route_provider, self._route_fallback
        ).replan(command)

    # -- internal helpers -----------------------------------------------------

    async def _build_feasible_days(
        self,
        command: PlanningCreateCommand,
        candidate_pois: tuple[Poi, ...],
        anchors: ResolvedTravelAnchors,
        route_cache: dict[tuple[str, ...], ProviderSuccess[RoutePlan]] | None = None,
        route_calls: list[int] | None = None,
    ) -> tuple[list[ItineraryDay], tuple[Poi, ...]]:
        trip = command.payload.trip
        day_count = (trip.end_date - trip.start_date).days + 1
        cache = route_cache if route_cache is not None else {}
        calls = route_calls if route_calls is not None else [0]
        pair_attempts = [0]
        last_infeasible: list[PlanningInfeasibleError] = []

        async def search(
            offset: int,
            remaining: tuple[Poi, ...],
            selected: tuple[Poi, ...],
            days: tuple[ItineraryDay, ...],
            unmatched_must_visits: frozenset[str],
        ) -> tuple[list[ItineraryDay], tuple[Poi, ...]] | None:
            if offset == day_count:
                if unmatched_must_visits:
                    return None
                return list(days), selected
            pairs = list(combinations(range(len(remaining)), 2))
            pairs.sort(
                key=lambda pair: (
                    -sum(
                        any(
                            text_matches(place, remaining[index].name)
                            for place in unmatched_must_visits
                        )
                        for index in pair
                    ),
                    pair[0] + pair[1],
                    pair,
                )
            )
            for first_index, second_index in pairs:
                if pair_attempts[0] >= MAX_PAIR_ATTEMPTS_PER_PLAN:
                    break
                pair_attempts[0] += 1
                try:
                    day = await self._day(
                        command, offset,
                        remaining[first_index], remaining[second_index],
                        anchors, cache, calls,
                    )
                except PlanningInfeasibleError as failure:
                    last_infeasible[:] = [failure]
                    continue
                chosen = (remaining[first_index], remaining[second_index])
                next_unmatched = frozenset(
                    place
                    for place in unmatched_must_visits
                    if not any(text_matches(place, poi.name) for poi in chosen)
                )
                removed = {first_index, second_index}
                next_remaining = tuple(
                    poi for index, poi in enumerate(remaining) if index not in removed
                )
                result = await search(
                    offset + 1, next_remaining, (*selected, *chosen),
                    (*days, day), next_unmatched,
                )
                if result is not None:
                    return result
            return None

        result = await search(
            0, candidate_pois, (), (),
            frozenset(trip.constraints.must_visit_places),
        )
        if result is not None:
            return result
        unmatched_must_visits = tuple(
            place
            for place in trip.constraints.must_visit_places
            if not any(text_matches(place, poi.name) for poi in candidate_pois)
        )
        if unmatched_must_visits:
            raise PlanningInfeasibleError(
                conflicts=(
                    OptimizationConflict(
                        "MUST_VISIT_UNAVAILABLE",
                        "必去地点无法与当前时间、路线或行动能力约束同时满足",
                        unmatched_must_visits,
                    ),
                ),
                relaxations=(
                    RelaxationSuggestion(
                        "ADJUST_TRAVEL_CONTEXT",
                        "调整到返时间、行动能力或其他必去地点后重试",
                    ),
                ),
            )
        if pair_attempts[0] >= MAX_PAIR_ATTEMPTS_PER_PLAN:
            raise PlanningProviderError("PAIR_ATTEMPT_BUDGET_EXHAUSTED")
        if last_infeasible:
            raise last_infeasible[-1]
        raise PlanningProviderError("INSUFFICIENT_AMAP_POIS")

    async def _resolve_travel_anchors(
        self, command: PlanningCreateCommand,
    ) -> ResolvedTravelAnchors:
        constraints = command.payload.trip.constraints
        resolved: dict[str, Poi] = {}
        for anchor in (
            constraints.arrival, constraints.departure, constraints.accommodation,
        ):
            if anchor is None or anchor.place_name in resolved:
                continue
            search = await self._map_provider.search_pois(
                PoiSearchRequest(
                    city=command.payload.trip.destination,
                    keyword=anchor.place_name,
                    limit=5,
                )
            )
            if isinstance(search, ProviderFailure):
                if search.error_code == "POI_NOT_FOUND":
                    raise self._anchor_unavailable(anchor.place_name)
                raise PlanningProviderError(search.error_code)
            if search.provider != "AMAP":
                raise PlanningProviderError("UNEXPECTED_MAP_PROVIDER")
            matching = next(
                (
                    poi
                    for poi in search.data
                    if text_matches(anchor.place_name, poi.name)
                ),
                None,
            )
            if matching is None:
                raise self._anchor_unavailable(anchor.place_name)
            resolved[anchor.place_name] = matching
        return ResolvedTravelAnchors(
            arrival=(
                resolved.get(constraints.arrival.place_name)
                if constraints.arrival is not None
                else None
            ),
            departure=(
                resolved.get(constraints.departure.place_name)
                if constraints.departure is not None
                else None
            ),
            accommodation=(
                resolved.get(constraints.accommodation.place_name)
                if constraints.accommodation is not None
                else None
            ),
        )

    @staticmethod
    def _anchor_unavailable(place_name: str) -> PlanningInfeasibleError:
        return PlanningInfeasibleError(
            conflicts=(
                OptimizationConflict(
                    "TRAVEL_ANCHOR_UNAVAILABLE",
                    "到返或住宿地点未能在地图中确认",
                    (place_name,),
                ),
            ),
            relaxations=(
                RelaxationSuggestion(
                    "CHECK_TRAVEL_ANCHOR",
                    "补充更完整的车站、机场或住宿名称后重试",
                ),
            ),
        )

    async def _collect_pois(
        self, command: PlanningCreateCommand, required_count: int
    ) -> tuple[Poi, ...]:
        trip = command.payload.trip
        candidates: list[Poi] = []
        keywords = candidate_keywords(
            trip.constraints.preferences, trip.constraints.must_visit_places,
        )
        required_preference_queries = max(
            1,
            min(
                len(tuple(dict.fromkeys(
                    item.strip()
                    for item in trip.constraints.preferences
                    if item.strip()
                ))),
                len(keywords),
            ),
        )
        for query_index, keyword in enumerate(keywords, start=1):
            search = await self._map_provider.search_pois(
                PoiSearchRequest(
                    city=trip.destination,
                    keyword=keyword,
                    limit=min(required_count * 3, 25),
                )
            )
            if isinstance(search, ProviderFailure):
                if search.error_code == "POI_NOT_FOUND":
                    continue
                raise PlanningProviderError(search.error_code)
            if search.provider != "AMAP":
                raise PlanningProviderError("UNEXPECTED_MAP_PROVIDER")
            candidates.extend(search.data)
            if query_index < required_preference_queries:
                continue
            ranking = self._candidate_ranker.rank(
                tuple(candidates),
                destination=trip.destination,
                preferences=trip.constraints.preferences,
                traveler_type=trip.constraints.traveler_type,
                limit=required_count,
                must_visit_places=trip.constraints.must_visit_places,
                avoid_places=trip.constraints.avoid_places,
                guide_statements=tuple(
                    f"{fact.statement} {fact.evidence}"
                    for fact in command.payload.guide_evidence.facts
                ),
            )
            if len(ranking.selected) >= required_count:
                return tuple(candidates)
        return tuple(candidates)

    async def _day(
        self,
        command: PlanningCreateCommand,
        offset: int,
        first_poi: Poi,
        second_poi: Poi,
        anchors: ResolvedTravelAnchors | None = None,
        route_cache: dict[tuple[str, ...], ProviderSuccess[RoutePlan]] | None = None,
        route_calls: list[int] | None = None,
    ) -> ItineraryDay:
        anchors = anchors or ResolvedTravelAnchors()
        cache = route_cache if route_cache is not None else {}
        calls = route_calls if route_calls is not None else [0]
        trip_date = command.payload.trip.start_date + timedelta(days=offset)
        constraints = command.payload.trip.constraints
        mobility_level = constraints.mobility_level
        route_mode = "DRIVING" if mobility_level == "STEP_FREE" else "WALKING"
        provisional_first_end = datetime.combine(
            trip_date, time(hour=11), tzinfo=CHINA_TIME_ZONE
        )
        route = await self._route_cached(
            RouteRequest(
                origin=first_poi.coordinates,
                destination=second_poi.coordinates,
                departure_at=provisional_first_end,
                origin_poi_id=first_poi.provider_id,
                destination_poi_id=second_poi.provider_id,
                mode=route_mode,
            ),
            cache, calls,
        )
        mobility_limit = {
            "STANDARD": None,
            "REDUCED": 2_000,
            "STEP_FREE": None,
        }[mobility_level]
        if mobility_limit is not None and route.data.distance_meters > mobility_limit:
            raise PlanningInfeasibleError(
                conflicts=(
                    OptimizationConflict(
                        "MOBILITY_ROUTE_TOO_LONG",
                        f"相邻活动步行距离 {route.data.distance_meters} 米超出行动能力上限",
                        (first_poi.name, second_poi.name),
                    ),
                ),
                relaxations=(
                    RelaxationSuggestion(
                        "CHANGE_MOBILITY_OR_TRANSPORT",
                        "调整地点组合或改用无障碍交通方式",
                    ),
                ),
            )
        available_start, available_end = available_minutes(
            trip_date,
            command.payload.trip.start_date,
            command.payload.trip.end_date,
            constraints.arrival.time if constraints.arrival is not None else None,
            constraints.departure.time if constraints.departure is not None else None,
        )
        origin_anchor = (
            anchors.arrival
            if (
                trip_date == command.payload.trip.start_date
                and anchors.arrival is not None
            )
            else anchors.accommodation
        )
        destination_anchor = (
            anchors.departure
            if (
                trip_date == command.payload.trip.end_date
                and anchors.departure is not None
            )
            else anchors.accommodation
        )
        if origin_anchor is not None:
            origin_route = await self._route_cached(
                RouteRequest(
                    origin=origin_anchor.coordinates,
                    destination=first_poi.coordinates,
                    departure_at=minute_datetime(trip_date, available_start),
                    origin_poi_id=origin_anchor.provider_id,
                    destination_poi_id=first_poi.provider_id,
                    mode="DRIVING",
                ),
                cache, calls,
            )
            available_start += ceil(origin_route.data.duration_seconds / 60)
        if destination_anchor is not None:
            destination_route = await self._route_cached(
                RouteRequest(
                    origin=second_poi.coordinates,
                    destination=destination_anchor.coordinates,
                    departure_at=minute_datetime(trip_date, available_end),
                    origin_poi_id=second_poi.provider_id,
                    destination_poi_id=destination_anchor.provider_id,
                    mode="DRIVING",
                ),
                cache, calls,
            )
            available_end -= ceil(destination_route.data.duration_seconds / 60)
        if available_start >= available_end:
            raise PlanningInfeasibleError(
                conflicts=(
                    OptimizationConflict(
                        "INSUFFICIENT_DAY_CAPACITY",
                        "到返时间没有留下可用的日间规划窗口",
                        (trip_date.isoformat(),),
                    ),
                ),
                relaxations=(
                    RelaxationSuggestion(
                        "EXTEND_AVAILABLE_TIME", "调整到达或返程时间"
                    ),
                ),
            )
        fixed_schedules = [
            TimeBlock(schedule.place_name, schedule.start_time, schedule.end_time)
            for schedule in constraints.fixed_schedules
        ]
        fixed_schedules.extend(
            TimeBlock(
                f"MEAL:{window.meal_type}",
                datetime.combine(trip_date, window.start_time, tzinfo=CHINA_TIME_ZONE),
                datetime.combine(trip_date, window.end_time, tzinfo=CHINA_TIME_ZONE),
            )
            for window in constraints.meal_windows
        )
        optimization = self._optimizer.optimize(
            DailyOptimizationRequest(
                date=trip_date,
                route_duration_seconds=route.data.duration_seconds,
                fixed_schedules=tuple(fixed_schedules),
                available_start_minute=available_start,
                available_end_minute=available_end,
            )
        )
        if optimization.status == "INFEASIBLE":
            raise PlanningInfeasibleError(
                optimization.conflicts, optimization.relaxations
            )
        if any(
            value is None
            for value in (
                optimization.first_start,
                optimization.first_end,
                optimization.second_start,
                optimization.second_end,
            )
        ):
            raise RuntimeError(
                "feasible optimizer result omitted schedule timestamps"
            )
        first_start = optimization.first_start
        first_end = optimization.first_end
        second_start = optimization.second_start
        second_end = optimization.second_end
        assert first_start is not None
        assert first_end is not None
        assert second_start is not None
        assert second_end is not None
        return ItineraryDay(
            date=trip_date,
            activities=(
                amap_activity(first_poi, first_start, first_end),
                amap_activity(second_poi, second_start, second_end),
            ),
            transit_legs=(
                TransitLeg(
                    from_activity_index=0,
                    to_activity_index=1,
                    mode=route.data.mode,
                    distance_meters=route.data.distance_meters,
                    duration_seconds=route.data.duration_seconds,
                    provider=route.provider,
                    estimated=route.estimated,
                    polyline=tuple(
                        ActivityCoordinates(
                            longitude=coordinate_decimal(point.longitude),
                            latitude=coordinate_decimal(point.latitude),
                        )
                        for point in route.data.polyline
                    ),
                ),
            ),
        )

    async def _route(self, request: RouteRequest) -> ProviderSuccess[RoutePlan]:
        result = await self._route_provider.get_route(request)
        if isinstance(result, ProviderFailure):
            result = await self._route_fallback.get_route(request)
        if isinstance(result, ProviderFailure):
            raise PlanningProviderError(result.error_code)
        if result.provider not in {"AMAP", "DEMO"}:
            raise PlanningProviderError("UNEXPECTED_ROUTE_PROVIDER")
        if (result.provider == "AMAP" and result.estimated) or (
            result.provider == "DEMO" and not result.estimated
        ):
            raise RuntimeError(
                "route provider returned inconsistent source metadata"
            )
        return result

    async def _route_cached(
        self,
        request: RouteRequest,
        cache: dict[tuple[str, ...], ProviderSuccess[RoutePlan]],
        calls: list[int],
    ) -> ProviderSuccess[RoutePlan]:
        key = (
            request.origin_poi_id or str(request.origin),
            request.destination_poi_id or str(request.destination),
            request.mode,
            request.departure_at.isoformat(),
        )
        cached = cache.get(key)
        if cached is not None:
            return cached
        if calls[0] >= MAX_ROUTE_CALLS_PER_PLAN:
            raise PlanningProviderError("ROUTE_CALL_BUDGET_EXHAUSTED")
        calls[0] += 1
        result = await self._route(request)
        cache[key] = result
        return result
