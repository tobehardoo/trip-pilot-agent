"""Pure planning command processing."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, timezone
from decimal import Decimal
from itertools import combinations
from math import ceil
from typing import Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from trip_agent.planning.candidates import CandidateRanker, is_positive_guide_statement
from trip_agent.planning.optimization import (
    DailyOptimizationRequest,
    DailyOptimizer,
    OptimizationConflict,
    RelaxationSuggestion,
    TimeBlock,
)
from trip_agent.providers.map import (
    MapProvider,
    MapProviderName,
    Poi,
    PoiSearchRequest,
    ProviderFailure,
    ProviderSuccess,
)
from trip_agent.providers.route import (
    DemoRouteProvider,
    RoutePlan,
    RouteProvider,
    RouteRequest,
)
from trip_agent.worker.contracts import (
    ActivityCoordinates,
    Itinerary,
    ItineraryActivity,
    ItineraryDay,
    KnowledgeCitationSnapshot,
    KnowledgeEvidence,
    KnowledgeFreshness,
    PlanningCompletedEvent,
    PlanningCompletedPayload,
    PlanningConflict,
    PlanningCreateCommand,
    PlanningFailedEvent,
    PlanningFailedPayload,
    PlanningRelaxation,
    TransitLeg,
)
from trip_agent.worker.knowledge import build_knowledge_query

CHINA_TIME_ZONE = timezone(timedelta(hours=8), name="Asia/Shanghai")
COORDINATE_SCALE = Decimal("0.0000001")
DEFAULT_POI_KEYWORDS = ("景点", "博物馆", "公园", "美食")
MAX_POI_QUERIES = 6
MAX_TRIP_DAYS = 7
MAX_PLANNING_CANDIDATES = MAX_TRIP_DAYS * 2
MAX_PAIR_ATTEMPTS_PER_PLAN = 48
MAX_ROUTE_CALLS_PER_PLAN = 96
AMAP_ACTIVITY_ESTIMATED_COST = Decimal("100.00")


class PlanningProvider(Protocol):
    async def plan(self, command: PlanningCreateCommand) -> "PlanningResult": ...


class KnowledgeEvidenceProvider(Protocol):
    async def get_evidence(self, command: PlanningCreateCommand) -> KnowledgeEvidence: ...


@dataclass(frozen=True)
class PlanningResult:
    provider: MapProviderName
    itinerary: Itinerary
    guide_fact_ids: tuple[UUID, ...] = ()


@dataclass(frozen=True)
class ResolvedTravelAnchors:
    arrival: Poi | None = None
    departure: Poi | None = None
    accommodation: Poi | None = None


class PlanningProviderError(Exception):
    """An expected provider failure that may use the configured fallback."""


class PlanningInfeasibleError(Exception):
    """Hard constraints cannot be satisfied and must be shown to the user."""

    def __init__(
        self,
        conflicts: tuple[OptimizationConflict, ...],
        relaxations: tuple[RelaxationSuggestion, ...],
    ) -> None:
        super().__init__(conflicts[0].message if conflicts else "No feasible itinerary")
        self.conflicts = conflicts
        self.relaxations = relaxations


class DemoPlanningProvider:
    async def plan(self, command: PlanningCreateCommand) -> PlanningResult:
        trip = command.payload.trip
        if trip.constraints.must_visit_places:
            raise PlanningInfeasibleError(
                conflicts=(OptimizationConflict(
                    "MUST_VISIT_UNVERIFIABLE_IN_DEMO",
                    "演示降级无法验证必去地点，已停止生成以避免返回不符合约束的行程",
                    trip.constraints.must_visit_places,
                ),),
                relaxations=(RelaxationSuggestion(
                    "RETRY_REAL_PROVIDER",
                    "地图服务恢复后重试，或移除必去地点约束",
                ),),
            )
        day_count = (trip.end_date - trip.start_date).days + 1
        days = tuple(self._day(command, offset) for offset in range(day_count))
        return PlanningResult(
            provider="DEMO",
            itinerary=Itinerary(
                title=f"{trip.destination} Demo 行程",
                days=days,
                estimated_total_cost=Decimal("0"),
            ),
        )

    def _day(self, command: PlanningCreateCommand, offset: int) -> ItineraryDay:
        trip = command.payload.trip
        trip_date = trip.start_date + timedelta(days=offset)
        constraints = trip.constraints
        available_start, available_end = _available_minutes(
            trip_date,
            trip.start_date,
            trip.end_date,
            constraints.arrival.time if constraints.arrival is not None else None,
            constraints.departure.time if constraints.departure is not None else None,
        )
        blocked = [
            (
                max(
                    available_start,
                    int(
                        (
                            schedule.start_time.astimezone(CHINA_TIME_ZONE)
                            - datetime.combine(trip_date, time.min, tzinfo=CHINA_TIME_ZONE)
                        ).total_seconds()
                        // 60
                    ),
                ),
                min(
                    available_end,
                    int(
                        (
                            schedule.end_time.astimezone(CHINA_TIME_ZONE)
                            - datetime.combine(trip_date, time.min, tzinfo=CHINA_TIME_ZONE)
                        ).total_seconds()
                        // 60
                    ),
                ),
            )
            for schedule in constraints.fixed_schedules
            if (
                schedule.start_time.astimezone(CHINA_TIME_ZONE)
                < datetime.combine(
                    trip_date + timedelta(days=1),
                    time.min,
                    tzinfo=CHINA_TIME_ZONE,
                )
                and schedule.end_time.astimezone(CHINA_TIME_ZONE)
                > datetime.combine(trip_date, time.min, tzinfo=CHINA_TIME_ZONE)
            )
        ]
        blocked.extend(
            (
                max(available_start, window.start_time.hour * 60 + window.start_time.minute),
                min(available_end, window.end_time.hour * 60 + window.end_time.minute),
            )
            for window in constraints.meal_windows
        )
        cursor = available_start
        for block_start, block_end in sorted(blocked):
            if block_start - cursor >= 120:
                break
            if block_end > cursor:
                cursor = block_end
        if available_end - cursor < 120:
            raise PlanningInfeasibleError(
                conflicts=(OptimizationConflict(
                    "INSUFFICIENT_DAY_CAPACITY",
                    "到返时间、固定安排和用餐时段之间没有两小时可用窗口",
                    (trip_date.isoformat(),),
                ),),
                relaxations=(RelaxationSuggestion(
                    "EXTEND_AVAILABLE_TIME",
                    "调整到返时间、固定安排或用餐时段后重试",
                ),),
            )
        start_time = _minute_datetime(trip_date, cursor)
        return ItineraryDay(
            date=trip_date,
            activities=(
                ItineraryActivity(
                    title="自主探索时段（演示）",
                    start_time=start_time,
                    end_time=start_time + timedelta(hours=2),
                    estimated_cost=Decimal("0"),
                    source="DEMO",
                ),
            ),
            transit_legs=(),
        )


class DemoKnowledgeEvidenceProvider:
    async def get_evidence(self, command: PlanningCreateCommand) -> KnowledgeEvidence:
        return KnowledgeEvidence(
            status="DEMO",
            query=build_knowledge_query(command),
            citations=(),
            freshness=KnowledgeFreshness(status="UNAVAILABLE"),
            message="演示模式未使用生产知识检索",
        )


class AmapPlanningProvider:
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
            if not any(_text_matches(place, poi.name) for poi in baseline_pois)
        )
        if unavailable_must_visits:
            raise PlanningInfeasibleError(
                conflicts=(OptimizationConflict(
                    "MUST_VISIT_UNAVAILABLE",
                    "必去地点未能在当前地图候选中确认",
                    unavailable_must_visits,
                ),),
                relaxations=(RelaxationSuggestion(
                    "REDUCE_OPTIONAL_ACTIVITIES", "移除无法确认的必去地点后重试"
                ),),
            )
        estimated_total_cost = AMAP_ACTIVITY_ESTIMATED_COST * required_pois
        budget = trip.constraints.budget_amount
        if budget is not None and estimated_total_cost > budget:
            raise PlanningInfeasibleError(
                conflicts=(OptimizationConflict(
                    "BUDGET_EXCEEDED",
                    f"预计活动费用 {estimated_total_cost:.2f} 超出预算 {budget:.2f}",
                    ("budgetAmount",),
                ),),
                relaxations=(
                    RelaxationSuggestion("INCREASE_BUDGET", "提高预算上限"),
                    RelaxationSuggestion("REDUCE_OPTIONAL_ACTIVITIES", "减少可选活动"),
                ),
            )
        anchors = await self._resolve_travel_anchors(command)
        route_cache: dict[tuple[str, ...], ProviderSuccess[RoutePlan]] = {}
        route_calls = [0]
        baseline_days, baseline_selected = await self._build_feasible_days(
            command,
            baseline_pois,
            anchors,
            route_cache,
            route_calls,
        )
        days, pois = baseline_days, baseline_selected
        guide_influenced = False
        if guide_statements and guided_pois != baseline_pois:
            try:
                days, pois = await self._build_feasible_days(
                    command,
                    guided_pois,
                    anchors,
                    route_cache,
                    route_calls,
                )
                guide_influenced = tuple(
                    poi.provider_id for poi in pois
                ) != tuple(poi.provider_id for poi in baseline_selected)
            except (PlanningInfeasibleError, PlanningProviderError):
                # Community facts are soft evidence: a guide-ranked alternative may
                # improve a feasible plan, but it must never invalidate the baseline.
                days, pois = baseline_days, baseline_selected
        unmatched_must_visits = tuple(
            place
            for place in trip.constraints.must_visit_places
            if not any(_text_matches(place, poi.name) for poi in pois)
        )
        if unmatched_must_visits:
            raise PlanningInfeasibleError(
                conflicts=(OptimizationConflict(
                    "MUST_VISIT_UNAVAILABLE",
                    "必去地点无法与当前时间、路线或行动能力约束同时满足",
                    unmatched_must_visits,
                ),),
                relaxations=(RelaxationSuggestion(
                    "ADJUST_TRAVEL_CONTEXT",
                    "调整到返时间、行动能力或其他必去地点后重试",
                ),),
            )
        return PlanningResult(
            provider="AMAP",
            itinerary=Itinerary(
                title=f"{trip.destination} 真实地点行程",
                days=tuple(days),
                estimated_total_cost=estimated_total_cost,
            ),
            guide_fact_ids=(
                _matched_guide_fact_ids(command, pois)
                if guide_influenced
                else ()
            ),
        )

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
                            _text_matches(place, remaining[index].name)
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
                        command,
                        offset,
                        remaining[first_index],
                        remaining[second_index],
                        anchors,
                        cache,
                        calls,
                    )
                except PlanningInfeasibleError as failure:
                    last_infeasible[:] = [failure]
                    continue
                chosen = (remaining[first_index], remaining[second_index])
                next_unmatched = frozenset(
                    place
                    for place in unmatched_must_visits
                    if not any(_text_matches(place, poi.name) for poi in chosen)
                )
                removed = {first_index, second_index}
                next_remaining = tuple(
                    poi for index, poi in enumerate(remaining) if index not in removed
                )
                result = await search(
                    offset + 1,
                    next_remaining,
                    (*selected, *chosen),
                    (*days, day),
                    next_unmatched,
                )
                if result is not None:
                    return result
            return None

        result = await search(
            0,
            candidate_pois,
            (),
            (),
            frozenset(trip.constraints.must_visit_places),
        )
        if result is not None:
            return result
        unmatched_must_visits = tuple(
            place
            for place in trip.constraints.must_visit_places
            if not any(_text_matches(place, poi.name) for poi in candidate_pois)
        )
        if unmatched_must_visits:
            raise PlanningInfeasibleError(
                conflicts=(OptimizationConflict(
                    "MUST_VISIT_UNAVAILABLE",
                    "必去地点无法与当前时间、路线或行动能力约束同时满足",
                    unmatched_must_visits,
                ),),
                relaxations=(RelaxationSuggestion(
                    "ADJUST_TRAVEL_CONTEXT",
                    "调整到返时间、行动能力或其他必去地点后重试",
                ),),
            )
        if pair_attempts[0] >= MAX_PAIR_ATTEMPTS_PER_PLAN:
            raise PlanningProviderError("PAIR_ATTEMPT_BUDGET_EXHAUSTED")
        if last_infeasible:
            raise last_infeasible[-1]
        raise PlanningProviderError("INSUFFICIENT_AMAP_POIS")

    async def _resolve_travel_anchors(
        self,
        command: PlanningCreateCommand,
    ) -> ResolvedTravelAnchors:
        constraints = command.payload.trip.constraints
        resolved: dict[str, Poi] = {}
        for anchor in (
            constraints.arrival,
            constraints.departure,
            constraints.accommodation,
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
                    if _text_matches(anchor.place_name, poi.name)
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
            conflicts=(OptimizationConflict(
                "TRAVEL_ANCHOR_UNAVAILABLE",
                "到返或住宿地点未能在地图中确认",
                (place_name,),
            ),),
            relaxations=(RelaxationSuggestion(
                "CHECK_TRAVEL_ANCHOR",
                "补充更完整的车站、机场或住宿名称后重试",
            ),),
        )

    async def _collect_pois(
        self, command: PlanningCreateCommand, required_count: int
    ) -> tuple[Poi, ...]:
        trip = command.payload.trip
        candidates: list[Poi] = []
        keywords = _candidate_keywords(
            trip.constraints.preferences,
            trip.constraints.must_visit_places,
        )
        required_preference_queries = max(
            1,
            min(
                len(tuple(dict.fromkeys(
                    item.strip() for item in trip.constraints.preferences if item.strip()
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
            cache,
            calls,
        )
        mobility_limit = {
            "STANDARD": None,
            "REDUCED": 2_000,
            "STEP_FREE": None,
        }[mobility_level]
        if mobility_limit is not None and route.data.distance_meters > mobility_limit:
            raise PlanningInfeasibleError(
                conflicts=(OptimizationConflict(
                    "MOBILITY_ROUTE_TOO_LONG",
                    f"相邻活动步行距离 {route.data.distance_meters} 米超出行动能力上限",
                    (first_poi.name, second_poi.name),
                ),),
                relaxations=(RelaxationSuggestion(
                    "CHANGE_MOBILITY_OR_TRANSPORT", "调整地点组合或改用无障碍交通方式"
                ),),
            )
        available_start, available_end = _available_minutes(
            trip_date,
            command.payload.trip.start_date,
            command.payload.trip.end_date,
            constraints.arrival.time if constraints.arrival is not None else None,
            constraints.departure.time if constraints.departure is not None else None,
        )
        origin_anchor = (
            anchors.arrival
            if trip_date == command.payload.trip.start_date and anchors.arrival is not None
            else anchors.accommodation
        )
        destination_anchor = (
            anchors.departure
            if trip_date == command.payload.trip.end_date and anchors.departure is not None
            else anchors.accommodation
        )
        if origin_anchor is not None:
            origin_route = await self._route_cached(
                RouteRequest(
                    origin=origin_anchor.coordinates,
                    destination=first_poi.coordinates,
                    departure_at=_minute_datetime(trip_date, available_start),
                    origin_poi_id=origin_anchor.provider_id,
                    destination_poi_id=first_poi.provider_id,
                    mode="DRIVING",
                ),
                cache,
                calls,
            )
            available_start += ceil(origin_route.data.duration_seconds / 60)
        if destination_anchor is not None:
            destination_route = await self._route_cached(
                RouteRequest(
                    origin=second_poi.coordinates,
                    destination=destination_anchor.coordinates,
                    departure_at=_minute_datetime(trip_date, available_end),
                    origin_poi_id=second_poi.provider_id,
                    destination_poi_id=destination_anchor.provider_id,
                    mode="DRIVING",
                ),
                cache,
                calls,
            )
            available_end -= ceil(destination_route.data.duration_seconds / 60)
        if available_start >= available_end:
            raise PlanningInfeasibleError(
                conflicts=(OptimizationConflict(
                    "INSUFFICIENT_DAY_CAPACITY",
                    "到返时间没有留下可用的日间规划窗口",
                    (trip_date.isoformat(),),
                ),),
                relaxations=(RelaxationSuggestion(
                    "EXTEND_AVAILABLE_TIME", "调整到达或返程时间"
                ),),
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
            raise PlanningInfeasibleError(optimization.conflicts, optimization.relaxations)
        if any(
            value is None
            for value in (
                optimization.first_start,
                optimization.first_end,
                optimization.second_start,
                optimization.second_end,
            )
        ):
            raise RuntimeError("feasible optimizer result omitted schedule timestamps")
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
                _amap_activity(first_poi, first_start, first_end),
                _amap_activity(second_poi, second_start, second_end),
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
                            longitude=_coordinate_decimal(point.longitude),
                            latitude=_coordinate_decimal(point.latitude),
                        )
                        for point in route.data.polyline
                    ),
                ),
            ),
        )

    async def _route(self, request: RouteRequest):
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
            raise RuntimeError("route provider returned inconsistent source metadata")
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


class FallbackPlanningProvider:
    def __init__(self, primary: PlanningProvider, fallback: PlanningProvider) -> None:
        self._primary = primary
        self._fallback = fallback

    async def plan(self, command: PlanningCreateCommand) -> PlanningResult:
        try:
            return await self._primary.plan(command)
        except PlanningProviderError:
            return await self._fallback.plan(command)


async def process_planning_create(
    command: PlanningCreateCommand,
    provider: PlanningProvider,
    *,
    knowledge_provider: KnowledgeEvidenceProvider | None = None,
    occurred_at: datetime | None = None,
) -> PlanningCompletedEvent:
    completed_at = occurred_at or datetime.now(UTC)
    effective_command = _command_with_fresh_guide_evidence(command, completed_at)
    result = await provider.plan(effective_command)
    knowledge = await (knowledge_provider or DemoKnowledgeEvidenceProvider()).get_evidence(
        effective_command
    )
    knowledge = _merge_guide_evidence(
        effective_command,
        result,
        knowledge,
        checked_at=completed_at,
    )
    return PlanningCompletedEvent(
        event_type="PLANNING_COMPLETED",
        schema_version=5,
        event_id=_completed_event_id(command.event_id),
        trace_id=command.trace_id,
        task_id=command.task_id,
        trip_id=command.trip_id,
        run_id=_run_id(command.task_id),
        occurred_at=completed_at,
        payload=PlanningCompletedPayload(
            provider=result.provider,
            itinerary=result.itinerary,
            knowledge=knowledge,
        ),
    )


def _command_with_fresh_guide_evidence(
    command: PlanningCreateCommand,
    checked_at: datetime,
) -> PlanningCreateCommand:
    fresh_facts = tuple(
        fact
        for fact in command.payload.guide_evidence.facts
        if fact.observed_at <= checked_at < fact.expires_at
    )
    if len(fresh_facts) == len(command.payload.guide_evidence.facts):
        return command
    guide_evidence = command.payload.guide_evidence.model_copy(
        update={"facts": fresh_facts}
    )
    payload = command.payload.model_copy(update={"guide_evidence": guide_evidence})
    return command.model_copy(update={"payload": payload})


def planning_failed_event(
    command: PlanningCreateCommand,
    failure: PlanningInfeasibleError,
    *,
    occurred_at: datetime | None = None,
) -> PlanningFailedEvent:
    return PlanningFailedEvent(
        event_type="PLANNING_FAILED",
        schema_version=1,
        event_id=_failed_event_id(command.event_id),
        trace_id=command.trace_id,
        task_id=command.task_id,
        trip_id=command.trip_id,
        run_id=_run_id(command.task_id),
        occurred_at=occurred_at or datetime.now(UTC),
        payload=PlanningFailedPayload(
            status="FAILED",
            error_code="NO_FEASIBLE_ITINERARY",
            message=str(failure),
            conflicts=tuple(
                PlanningConflict(
                    code=item.code,
                    message=item.message,
                    affected=item.affected,
                )
                for item in failure.conflicts
            ),
            relaxation_suggestions=tuple(
                PlanningRelaxation(code=item.code, message=item.message)
                for item in failure.relaxations
            ),
        ),
    )


def _completed_event_id(command_event_id: UUID) -> UUID:
    return uuid5(NAMESPACE_URL, f"trip-pilot/planning-completed/{command_event_id}")


def _failed_event_id(command_event_id: UUID) -> UUID:
    return uuid5(NAMESPACE_URL, f"trip-pilot/planning-failed/{command_event_id}")


def _run_id(task_id: UUID) -> UUID:
    return uuid5(NAMESPACE_URL, f"trip-pilot/agent-run/{task_id}")


def _coordinate_decimal(value: float) -> Decimal:
    return Decimal(str(value)).quantize(COORDINATE_SCALE)


def _amap_activity(poi: Poi, start_time: datetime, end_time: datetime) -> ItineraryActivity:
    return ItineraryActivity(
        title=poi.name,
        start_time=start_time,
        end_time=end_time,
        estimated_cost=AMAP_ACTIVITY_ESTIMATED_COST,
        source="AMAP",
        provider_poi_id=poi.provider_id,
        coordinates=ActivityCoordinates(
            longitude=_coordinate_decimal(poi.coordinates.longitude),
            latitude=_coordinate_decimal(poi.coordinates.latitude),
        ),
        address=poi.address,
    )


def _candidate_keywords(
    preferences: tuple[str, ...],
    must_visit_places: tuple[str, ...] = (),
) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys((*must_visit_places, *preferences, *DEFAULT_POI_KEYWORDS))
    )[:MAX_POI_QUERIES]


def _text_matches(expected: str, actual: str) -> bool:
    expected_key = "".join(character for character in expected.casefold() if character.isalnum())
    actual_key = "".join(character for character in actual.casefold() if character.isalnum())
    return bool(expected_key) and (expected_key in actual_key or actual_key in expected_key)


def _matched_guide_fact_ids(
    command: PlanningCreateCommand,
    pois: tuple[Poi, ...],
) -> tuple[UUID, ...]:
    return tuple(
        fact.fact_id
        for fact in command.payload.guide_evidence.facts
        if is_positive_guide_statement(f"{fact.statement} {fact.evidence}")
        and any(
            _text_matches(poi.name, f"{fact.statement} {fact.evidence}")
            for poi in pois
        )
    )


def _available_minutes(
    trip_date: date,
    start_date: date,
    end_date: date,
    arrival: datetime | None,
    departure: datetime | None,
) -> tuple[int, int]:
    start_minute = 9 * 60
    end_minute = 18 * 60
    if trip_date == start_date and arrival is not None:
        local_arrival = arrival.astimezone(CHINA_TIME_ZONE)
        start_minute = max(start_minute, local_arrival.hour * 60 + local_arrival.minute)
    if trip_date == end_date and departure is not None:
        local_departure = departure.astimezone(CHINA_TIME_ZONE)
        end_minute = min(end_minute, local_departure.hour * 60 + local_departure.minute)
    return start_minute, end_minute


def _minute_datetime(day: date, minute_of_day: int) -> datetime:
    return datetime.combine(day, time.min, tzinfo=CHINA_TIME_ZONE) + timedelta(
        minutes=minute_of_day
    )


def _merge_guide_evidence(
    command: PlanningCreateCommand,
    result: PlanningResult,
    knowledge: KnowledgeEvidence,
    *,
    checked_at: datetime,
) -> KnowledgeEvidence:
    used_ids = set(result.guide_fact_ids)
    facts = tuple(
        fact
        for fact in command.payload.guide_evidence.facts
        if fact.fact_id in used_ids
    )
    if not facts:
        return knowledge
    guide_citations = tuple(
        KnowledgeCitationSnapshot(
            document_id=str(fact.guide_import_id),
            document_version=1,
            chunk_id=str(fact.fact_id),
            chunk_index=index,
            title=f"{fact.source_title}｜{fact.statement}"[:200],
            source_url=fact.source_url,
            source_name=fact.source_host[:120],
            collected_at=fact.observed_at,
            reliability_level="community-guide",
            similarity=fact.confidence,
        )
        for index, fact in enumerate(facts)
    )
    citations = (
        (*guide_citations, *knowledge.citations)
        if knowledge.status == "REAL"
        else guide_citations
    )[:20]
    freshness = (
        knowledge.freshness
        if knowledge.status == "REAL"
        else KnowledgeFreshness(status="FRESH", checked_at=checked_at)
    )
    return KnowledgeEvidence(
        status="REAL",
        query=knowledge.query,
        citations=citations,
        freshness=freshness,
    )
