"""AMap-based planning provider — real POI search, route queries, and scheduling.

This provider depends on AMap web-service APIs for POI search and route
planning, on the candidate ranker for scoring, and on the pure daily-schedule
module (:mod:`trip_agent.planning.daily_schedule`) for deterministic daily
plans (day types, anchors, meal demand, capacity).
"""

import logging
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID, uuid5

from trip_agent.domain.planning.protocols import (
    OptimizationConflict,
    PlanningInfeasibleError,
    PlanningProviderError,
    PlanningResult,
    RelaxationSuggestion,
    ResolvedTravelAnchors,
)
from trip_agent.domain.shared import (
    AMAP_ACTIVITY_ESTIMATED_COST,
    CHINA_TIME_ZONE,
    MAX_ROUTE_CALLS_PER_PLAN,
    candidate_keywords,
    coordinate_decimal,
    minute_datetime,
    text_matches,
)
from trip_agent.guide_intelligence.travel_entities import (
    FactProvenance,
    FactValue,
    TravelEntityLocation,
    build_attraction,
)
from trip_agent.planning.candidates import CandidateRanker
from trip_agent.planning.daily_schedule import (
    CandidateActivity,
    DayPlan,
    DayPlanItem,
    FixedSchedule,
    MealDemand,
    classify_day_type,
    plan_day,
)
from trip_agent.planning.poi_quality import (
    activity_candidate_eligible,
    canonical_poi_key,
    duration_profile_for,
    magnitude_for_duration,
)
from trip_agent.planning.trusted_context import hard_closed_fact
from trip_agent.providers.errors import (
    FallbackDecision,
    ProviderExecutionMode,
    ProviderFallbackPolicy,
    ProviderOperation,
)
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
    FallbackOperation,
    GuideFactEvidence,
    Itinerary,
    ItineraryActivity,
    ItineraryDay,
    PlanningCreateCommand,
    PlanningReplanCommand,
    TransitLeg,
)
from trip_agent.worker.progress import report_planning_progress

logger = logging.getLogger(__name__)

_REDUCED_MOBILITY_MAX_HOP_METERS = 3_000
_MAX_MOBILITY_REPAIR_ATTEMPTS = 2

def _entity_facts_for_pois(
    pois: tuple[Poi, ...],
    command: PlanningCreateCommand,
) -> tuple:
    """Project fresh planning-context opening-hour facts onto recalled POIs.

    The event contract predates ``cityAdcode``; keep that field explicitly unknown
    until the producer supplies the structured region, while still preserving the
    fact's source and expiry for candidate explanations.
    """
    context = command.payload.planning_context
    if context is None:
        return ()
    opening_facts = tuple(
        fact for fact in context.facts
        if fact.category == "OPENING_HOURS" and not fact.stale
    )
    entities = []
    for poi in pois:
        fact = next(
            (
                item for item in opening_facts
                if text_matches(poi.name, f"{item.statement} {item.evidence}")
            ),
            None,
        )
        if fact is None:
            continue
        source_type = "OFFICIAL" if fact.source_reviewed else "GUIDE"
        provenance = FactProvenance(
            source=fact.source_name,
            source_type=source_type,
            fetched_at=fact.checked_at,
            valid_until=fact.expires_at,
            confidence=1.0 if fact.source_reviewed else 0.7,
        )
        entities.append(
            build_attraction(
                city_adcode=None,
                provider_poi_id=poi.provider_id,
                name=poi.name,
                category="ATTRACTION",
                location=TravelEntityLocation(
                    poi.coordinates.longitude,
                    poi.coordinates.latitude,
                    poi.address,
                ),
                opening_hours=FactValue.known(fact.statement, provenance),
            )
        )
    return tuple(entities)
_COMPLEX_TERMS = (
    "泰山", "华山", "衡山", "黄山", "庐山", "峨眉", "峡谷",
    "迪士尼", "迪斯尼", "长隆", "乐园", "环球影城", "主题公园", "度假区", "古镇",
)
_DINING_TERMS = ("美食", "餐饮", "小吃", "火锅", "面馆", "粤菜", "咖啡", "茶")


def _non_weather_guide_statements(
    facts: tuple[GuideFactEvidence, ...],
) -> tuple[str, ...]:
    return tuple(
        f"{fact.statement} {fact.evidence}"
        for fact in facts
        if fact.category != "WEATHER"
    )


def weather_statements_for_date(
    facts: tuple[GuideFactEvidence, ...],
    trip_date: date,
) -> tuple[str, ...]:
    """Return only structured weather evidence that applies to one trip day."""
    return tuple(
        f"{fact.statement} {fact.evidence}"
        for fact in facts
        if fact.category == "WEATHER" and fact.effective_date == trip_date
    )


class AmapPlanningProvider:
    """Generates a real itinerary using AMap web-service APIs.

    Uses AMap POI search for candidate discovery, AMap route planning for
    inter‑activity transit, a deterministic :class:`CandidateRanker` for
    scoring, and the pure daily-schedule module for deterministic daily plans.
    """

    def __init__(
        self,
        map_provider: MapProvider,
        route_provider: RouteProvider,
        route_fallback: RouteProvider | None = None,
        candidate_ranker: CandidateRanker | None = None,
        provider_mode: ProviderExecutionMode = ProviderExecutionMode.REAL_ONLY,
        fallback_policy: ProviderFallbackPolicy | None = None,
    ) -> None:
        self._map_provider = map_provider
        self._route_provider = route_provider
        self._route_fallback = route_fallback
        self._candidate_ranker = candidate_ranker or CandidateRanker()
        self._provider_mode = provider_mode
        self._fallback_policy = fallback_policy or ProviderFallbackPolicy()

    # -- public API -----------------------------------------------------------

    async def plan(self, command: PlanningCreateCommand) -> PlanningResult:
        return await self._plan_with_skeleton(command)

    # -- daily-skeleton scheduling path ----------------------------------------

    async def _plan_with_skeleton(
        self, command: PlanningCreateCommand
    ) -> PlanningResult:
        trip = command.payload.trip
        constraints = trip.constraints
        day_count = (trip.end_date - trip.start_date).days + 1
        await report_planning_progress(
            "POI_RECALLING",
            "Loading destination points of interest",
            {"requiredPoiCount": day_count * 3},
        )
        raw_pois = await self._collect_pois(command, max(day_count * 3, 2))
        if not raw_pois:
            raise PlanningProviderError("INSUFFICIENT_AMAP_POIS")
        # Candidate quality: drop pure infrastructure (bus stops, parking,
        # metro, station gates) before ranking.  Transport hubs that serve as
        # arrival/departure anchors are resolved separately and kept.
        activity_pois = tuple(
            poi for poi in raw_pois if activity_candidate_eligible(poi)
        )
        if not activity_pois:
            raise PlanningProviderError("INSUFFICIENT_AMAP_POIS")
        ranking = self._candidate_ranker.rank(
            activity_pois,
            destination=trip.destination,
            preferences=constraints.preferences,
            traveler_type=constraints.traveler_type,
            limit=len(raw_pois),
            must_visit_places=constraints.must_visit_places,
            avoid_places=constraints.avoid_places,
            guide_statements=_non_weather_guide_statements(
                command.payload.guide_evidence.facts
            ),
            entity_facts=_entity_facts_for_pois(raw_pois, command),
        )
        ranked_pois = tuple(item.poi for item in ranking.selected)
        poi_by_id = {poi.provider_id: poi for poi in ranked_pois}
        score_by_id = {
            item.poi.provider_id: item.score for item in ranking.selected
        }
        must_visit_text = set(constraints.must_visit_places)
        candidates = tuple(
            self._to_candidate(poi, must_visit_text, score_by_id)
            for poi in ranked_pois
        )
        # Canonical identity per candidate: used for cross-day dedup so that
        # sub-facilities of the same place (光孝寺 vs 光孝寺-六祖殿) collapse
        # into one, while genuinely distinct attractions stay apart.
        canonical_key_by_id = {
            poi.provider_id: canonical_poi_key(poi)
            for poi in ranked_pois
        }
        anchors = await self._resolve_travel_anchors(command)
        special_date = self._special_day_date(command, candidates)

        route_cache: dict[tuple[str, ...], ProviderSuccess[RoutePlan]] = {}
        route_calls = [0]
        itinerary_days: list[ItineraryDay] = []
        warnings: list[str] = []
        total_cost = Decimal("0")
        context = command.payload.planning_context
        closure_filtered_must: set[str] = set()
        remaining_candidates = candidates
        for offset in range(day_count):
            trip_date = trip.start_date + timedelta(days=offset)
            has_full = trip_date == special_date
            day_candidates = (
                remaining_candidates
                if has_full or special_date is None
                else tuple(
                    candidate
                    for candidate in remaining_candidates
                    if candidate.magnitude != "FULL_DAY"
                )
            )
            if context is not None:
                day_candidates = tuple(
                    candidate
                    for candidate in day_candidates
                    if hard_closed_fact(context, trip_date, candidate.title) is None
                )
                for candidate in candidates:
                    if (
                        candidate.must_include
                        and hard_closed_fact(
                            context, trip_date, candidate.title
                        ) is not None
                    ):
                        closure_filtered_must.add(candidate.poi_id)
            mobility_reduced = constraints.mobility_level == "REDUCED"
            for repair_attempt in range(_MAX_MOBILITY_REPAIR_ATTEMPTS + 1):
                day_plan = plan_day(
                    trip_date=trip_date,
                    start_date=trip.start_date,
                    end_date=trip.end_date,
                    arrival=(
                        constraints.arrival.time
                        if constraints.arrival is not None else None
                    ),
                    departure=(
                        constraints.departure.time
                        if constraints.departure is not None else None
                    ),
                    accommodation_known=anchors.accommodation is not None,
                    fixed_schedules=self._fixed_schedules_on(
                        constraints.fixed_schedules, trip_date
                    ),
                    candidates=day_candidates,
                    has_full_day_experience=has_full,
                    pace=constraints.pace,
                    mobility_reduced=mobility_reduced,
                    meal_preferences=constraints.preferences,
                )
                day, day_cost, day_warnings = await self._emit_day(
                    command, offset, day_plan, anchors, poi_by_id,
                    route_cache, route_calls,
                )
                rejected_poi_id = (
                    self._mobility_repair_candidate(day, day_candidates)
                    if mobility_reduced else None
                )
                if (
                    rejected_poi_id is None
                    or repair_attempt == _MAX_MOBILITY_REPAIR_ATTEMPTS
                ):
                    break
                day_candidates = tuple(
                    candidate
                    for candidate in day_candidates
                    if candidate.poi_id != rejected_poi_id
                )
            itinerary_days.append(day)
            total_cost += day_cost
            warnings.extend(day_warnings)
            placed_on_day = {
                key
                for activity in day.activities
                if activity.kind in {"ATTRACTION", "EXPERIENCE"}
                and activity.provider_poi_id is not None
                for key in (canonical_key_by_id.get(activity.provider_poi_id),)
                if key is not None
            }
            remaining_candidates = tuple(
                candidate
                for candidate in remaining_candidates
                if canonical_key_by_id.get(candidate.poi_id) not in placed_on_day
            )

        placed_ids = {
            activity.provider_poi_id
            for day in itinerary_days
            for activity in day.activities
            if activity.provider_poi_id is not None
        }
        must_visit_unplaced = tuple(
            candidate.title
            for candidate in candidates
            if candidate.must_include and candidate.poi_id not in placed_ids
        )
        closure_unplaced = tuple(
            candidate.title
            for candidate in candidates
            if candidate.must_include
            and candidate.poi_id in closure_filtered_must
            and candidate.poi_id not in placed_ids
        )
        if closure_unplaced:
            raise PlanningInfeasibleError(
                conflicts=(
                    OptimizationConflict(
                        "MUST_VISIT_UNAVAILABLE",
                        "必去地点在对应行程日期被官方临时关闭，无法安排",
                        closure_unplaced,
                    ),
                ),
                relaxations=(
                    RelaxationSuggestion(
                        "ADJUST_TRAVEL_CONTEXT",
                        "调整行程日期或更换必去地点后重试",
                    ),
                ),
            )
        if must_visit_unplaced:
            raise PlanningInfeasibleError(
                conflicts=(
                    OptimizationConflict(
                        "MUST_VISIT_UNAVAILABLE",
                        "必去地点无法与当前时间、路线或行动能力约束同时满足",
                        must_visit_unplaced,
                    ),
                ),
                relaxations=(
                    RelaxationSuggestion(
                        "ADJUST_TRAVEL_CONTEXT",
                        "调整到返时间、行动能力或其他必去地点后重试",
                    ),
                ),
            )
        actual_providers = tuple(sorted({
            "AMAP",
            *(leg.provider for day in itinerary_days for leg in day.transit_legs),
        }))
        fallback_operations = tuple(
            leg.fallback_operation
            for day in itinerary_days
            for leg in day.transit_legs
            if leg.fallback_operation is not None
        )
        itinerary = Itinerary(
            title=f"{trip.destination} 真实地点行程",
            days=tuple(itinerary_days),
            estimated_total_cost=total_cost,
        )
        return PlanningResult(
            provider="AMAP",
            itinerary=itinerary,
            guide_fact_ids=(),
            requested_provider_mode=self._provider_mode.value,
            primary_provider="AMAP",
            actual_providers=actual_providers,
            fallback_attempted=bool(fallback_operations),
            fallback_succeeded=bool(fallback_operations),
            fallback_reason=(
                "ROUTE_PROVIDER_FAILURE" if fallback_operations else None
            ),
            fallback_operations=fallback_operations,
        )

    @staticmethod
    def _is_must_visit_poi(poi: Poi, must_visit_text: set[str]) -> bool:
        """Decide whether a recalled POI is the user's must-visit place.

        Uses an exact (normalised) name match instead of a substring match so
        that AMap child facilities — e.g. ``光孝寺(公交站)``, ``光孝寺-六祖殿``,
        ``光孝寺售票处`` — are NOT mistaken for the attraction itself.  The
        must-visit intent refers to the named place, not its sub-POIs.
        """
        normalised = "".join(
            character for character in poi.name.casefold() if character.isalnum()
        )
        return any(
            "".join(
                character for character in place.casefold()
                if character.isalnum()
            ) == normalised
            for place in must_visit_text
        )

    def _to_candidate(
        self,
        poi: Poi,
        must_visit_text: set[str],
        score_by_id: dict[str, int],
    ) -> CandidateActivity:
        must = AmapPlanningProvider._is_must_visit_poi(poi, must_visit_text)
        magnitude = AmapPlanningProvider._magnitude_for_poi(poi)
        kind: str = (
            "EXPERIENCE"
            if magnitude in {"FULL_DAY", "HALF_DAY"}
            and AmapPlanningProvider._is_complex_experience(poi)
            else "ATTRACTION"
        )
        return CandidateActivity(
            poi_id=poi.provider_id,
            title=poi.name,
            magnitude=magnitude,
            coordinates=(
                float(poi.coordinates.longitude),
                float(poi.coordinates.latitude),
            ),
            region=poi.district or None,
            must_include=must,
            kind=kind,  # type: ignore[arg-type]
            score=score_by_id.get(poi.provider_id, 0),
        )

    @staticmethod
    def _magnitude_for_poi(poi: Poi) -> str:
        return magnitude_for_duration(duration_profile_for(poi))

    @staticmethod
    def _is_complex_experience(poi: Poi) -> bool:
        text = f"{poi.name} {poi.type_name}"
        return any(term in text for term in _COMPLEX_TERMS)

    @staticmethod
    def _fixed_schedules_on(
        fixed_schedules: tuple[FixedSchedule, ...],
        trip_date: date,
    ) -> tuple[FixedSchedule, ...]:
        """Keep the schedules that fall on ``trip_date``.

        ``constraints.fixed_schedules`` are the worker-contract schedules with
        ``place_name``/``start_time``/``end_time``; the scheduler consumes
        ``planning.daily_schedule.FixedSchedule`` (``label``/``start``/``end``),
        so we map fields while filtering by day.
        """
        from trip_agent.planning.daily_schedule import (
            FixedSchedule as DailyFixedSchedule,
        )

        return tuple(
            DailyFixedSchedule(
                label=schedule.place_name,
                start=schedule.start_time,
                end=schedule.end_time,
            )
            for schedule in fixed_schedules
            if schedule.start_time.astimezone(CHINA_TIME_ZONE).date() == trip_date
        )

    @staticmethod
    def _mobility_repair_candidate(
        day: ItineraryDay,
        candidates: tuple[CandidateActivity, ...],
    ) -> str | None:
        candidate_by_id = {candidate.poi_id: candidate for candidate in candidates}
        for leg in day.transit_legs:
            if leg.distance_meters <= _REDUCED_MOBILITY_MAX_HOP_METERS:
                continue
            endpoints = (
                day.activities[leg.to_activity_index],
                day.activities[leg.from_activity_index],
            )
            for activity in endpoints:
                poi_id = activity.provider_poi_id
                candidate = candidate_by_id.get(poi_id) if poi_id else None
                if candidate is not None and not candidate.must_include:
                    return candidate.poi_id
        return None

    @staticmethod
    def _special_day_date(
        command: PlanningCreateCommand,
        candidates: tuple[CandidateActivity, ...],
    ) -> date | None:
        if not any(c.magnitude == "FULL_DAY" for c in candidates):
            return None
        trip = command.payload.trip
        constraints = trip.constraints
        for offset in range((trip.end_date - trip.start_date).days + 1):
            trip_date = trip.start_date + timedelta(days=offset)
            day_type = classify_day_type(
                trip_date, trip.start_date, trip.end_date,
                constraints.arrival.time if constraints.arrival is not None else None,
                constraints.departure.time if constraints.departure is not None else None,
            )
            if day_type == "FULL_DAY":
                return trip_date
        return trip.start_date + timedelta(days=1)

    async def _emit_day(
        self,
        command: PlanningCreateCommand,
        offset: int,
        day_plan: DayPlan,
        anchors: ResolvedTravelAnchors,
        poi_by_id: dict[str, Poi],
        route_cache: dict[tuple[str, ...], ProviderSuccess[RoutePlan]],
        route_calls: list[int],
    ) -> tuple[ItineraryDay, Decimal, tuple[str, ...]]:
        trip_date = command.payload.trip.start_date + timedelta(days=offset)
        slots: list[dict[str, object]] = []
        unresolved: list[str] = []
        for item in day_plan.items:
            if item.kind == "ARRIVAL" and anchors.arrival is not None:
                slots.append(self._slot_from_item(item, anchors.arrival, trip_date, 0))
            elif item.kind == "DEPARTURE" and anchors.departure is not None:
                slots.append(self._slot_from_item(item, anchors.departure, trip_date, 0))
            elif item.kind == "MEAL" and item.meal is not None:
                restaurant = await self._resolve_meal_poi(item.meal, command)
                if restaurant is not None:
                    slots.append(self._slot_from_item(
                        item, restaurant, trip_date,
                        Decimal("0"), title=restaurant.name,
                    ))
                else:
                    label = "午餐" if item.meal.meal_type == "LUNCH" else "晚餐"
                    slots.append(self._slot_from_item(
                        item, None, trip_date, Decimal("0"),
                        title=f"{label}（建议在当前区域自行选择餐馆）",
                    ))
                    unresolved.append("MEAL_POI_UNRESOLVED")
            else:
                poi = poi_by_id.get(item.poi_id) if item.poi_id else None
                # Fixed arrangements (place-level schedules) are not recalled
                # with the candidate POIs; resolve their location so the node
                # is a real AMAP activity and transit endpoints stay continuous.
                if poi is None and item.time_fixed and item.kind == "ATTRACTION":
                    poi = await self._resolve_fixed_place(item.title, command)
                cost = (
                    Decimal("0")
                    if item.kind in {"ARRIVAL", "DEPARTURE", "ACCOMMODATION", "MEAL"}
                    else AMAP_ACTIVITY_ESTIMATED_COST
                )
                slots.append(self._slot_from_item(item, poi, trip_date, cost))

        day_count = (
            command.payload.trip.end_date - command.payload.trip.start_date
        ).days + 1
        if day_count > 1:
            hotel = anchors.accommodation
            start_time = minute_datetime(
                trip_date, day_plan.window_start_minute
            )
            end_slot = minute_datetime(trip_date, day_plan.window_end_minute)
            hotel_label = hotel.name if hotel is not None else "住宿地点待确认"
        if day_count > 1 and offset > 0:
            slots.insert(0, {
                "title": f"从{hotel_label}出发",
                "start": start_time - timedelta(minutes=15),
                "end": start_time,
                "poi": hotel,
                "kind": "ACCOMMODATION",
                "time_fixed": False,
                "magnitude": None,
                "cost": Decimal("0"),
            })
        if day_count > 1 and offset < day_count - 1:
            slots.append({
                "title": f"返回{hotel_label}",
                "start": end_slot,
                "end": end_slot + timedelta(minutes=15),
                "poi": hotel,
                "kind": "ACCOMMODATION",
                "time_fixed": False,
                "magnitude": None,
                "cost": Decimal("0"),
            })

        legs: list[tuple[int, int, ProviderSuccess[RoutePlan]]] = []
        for index in range(len(slots) - 1):
            origin = slots[index]
            destination = slots[index + 1]
            origin_poi = origin.get("poi")
            destination_poi = destination.get("poi")
            if origin_poi is None or destination_poi is None:
                continue
            route = await self._route_cached(
                RouteRequest(
                    origin=origin_poi.coordinates,
                    destination=destination_poi.coordinates,
                    departure_at=origin["end"],
                    origin_poi_id=origin_poi.provider_id,
                    destination_poi_id=destination_poi.provider_id,
                    mode="DRIVING",
                ),
                route_cache, route_calls,
            )
            # forward-fit: shift the destination and everything after it so the
            # real transit duration fits between activities.
            gap_seconds = (
                destination["start"] - origin["end"]
            ).total_seconds()
            if gap_seconds < route.data.duration_seconds:
                shift = timedelta(
                    seconds=route.data.duration_seconds - gap_seconds
                )
                for later in slots[index + 1:]:
                    later["start"] = later["start"] + shift
                    later["end"] = later["end"] + shift
            legs.append((index, index + 1, route))

        activities = tuple(
            self._activity_from_slot(slot, trip_date, command.task_id, index)
            for index, slot in enumerate(slots)
        )
        transit_legs = tuple(
            self._leg_from_route(
                command.task_id, trip_date, from_index, to_index, route,
            )
            for from_index, to_index, route in legs
        )
        total_cost = sum(
            (slot.get("cost") or Decimal("0")) for slot in slots
        )
        return (
            ItineraryDay(
                date=trip_date,
                day_type=day_plan.day_type,
                activities=activities,
                transit_legs=transit_legs,
            ),
            total_cost,
            tuple(unresolved),
        )

    def _slot_from_item(
        self,
        item: DayPlanItem,
        poi: Poi | None,
        trip_date: date,
        cost: Decimal,
        *,
        title: str | None = None,
    ) -> dict[str, object]:
        return {
            "title": title or item.title,
            "start": minute_datetime(trip_date, item.start_minute),
            "end": minute_datetime(trip_date, item.end_minute),
            "poi": poi,
            "kind": item.kind,
            "time_fixed": item.time_fixed,
            "magnitude": item.magnitude,
            "cost": cost,
        }

    def _activity_from_slot(
        self, slot: dict[str, object], trip_date: date, task_id: UUID, index: int
    ) -> ItineraryActivity:
        poi = slot.get("poi")
        title = str(slot["title"])
        start = slot["start"]
        end = slot["end"]
        kind = str(slot["kind"])
        time_fixed = bool(slot["time_fixed"])
        if poi is not None:
            activity_id = uuid5(
                task_id,
                f"activity:{trip_date}:{poi.provider_id}:{index}:{start.isoformat()}",
            )
            return ItineraryActivity(
                activity_id=activity_id,
                title=title,
                start_time=start,
                end_time=end,
                estimated_cost=Decimal(str(slot["cost"])),
                source="AMAP",
                provider_poi_id=poi.provider_id,
                coordinates=ActivityCoordinates(
                    longitude=coordinate_decimal(poi.coordinates.longitude),
                    latitude=coordinate_decimal(poi.coordinates.latitude),
                ),
                address=poi.address,
                type_code=poi.type_code,
                type_name=poi.type_name,
                kind=kind,  # type: ignore[arg-type]
                time_fixed=time_fixed,
            )
        return ItineraryActivity(
            activity_id=uuid5(
                task_id,
                f"activity:{trip_date}:{title}:{index}:{start.isoformat()}",
            ),
            title=title,
            start_time=start,
            end_time=end,
            estimated_cost=Decimal(str(slot["cost"])),
            source="AMAP",
            kind=kind,  # type: ignore[arg-type]
            time_fixed=time_fixed,
        )

    def _leg_from_route(
        self,
        task_id: UUID,
        trip_date: date,
        from_index: int,
        to_index: int,
        route: ProviderSuccess[RoutePlan],
    ) -> TransitLeg:
        transit_id = uuid5(
            task_id,
            f"transit:{trip_date}:{from_index}:{to_index}:{route.data.mode}",
        )
        fallback_operation = (
            FallbackOperation(
                operation="ROUTE",
                transit_id=transit_id,
                from_activity_id=None,
                to_activity_id=None,
                requested_mode="REAL_WITH_EXPLICIT_FALLBACK",
                actual_provider="DEMO",
                error_category=route.fallback_error.category.value,
                error_code=route.fallback_error.error_code,
                retry_count=route.fallback_error.retry_count,
            )
            if route.fallback_error is not None
            else None
        )
        cost = self._transit_cost(route.data)
        if route.provider == "DEMO" and cost is None:
            cost = Decimal("0.00")
        return TransitLeg(
            transit_id=transit_id,
            from_activity_index=from_index,
            to_activity_index=to_index,
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
            estimated_cost=cost,
            cost_source=self._transit_cost_source(route),
            fallback_operation=fallback_operation,
        )

    async def _resolve_fixed_place(
        self,
        place_name: str,
        command: PlanningCreateCommand,
    ) -> Poi | None:
        """Resolve a fixed-arrangement place to a real POI.

        Fixed schedules carry a user-provided place name but no provider POI.
        Search the destination so the scheduled node gets a real AMap identity,
        coordinates, and transit endpoints.  Returns ``None`` when the place is
        not found so the caller degrades gracefully (unresolved node).
        """
        trip = command.payload.trip
        search = await self._map_provider.search_pois(
            PoiSearchRequest(
                city=trip.destination,
                keyword=place_name,
                limit=5,
            )
        )
        if isinstance(search, ProviderFailure) or not search.data:
            return None
        matching = next(
            (
                poi
                for poi in search.data
                if text_matches(place_name, poi.name)
            ),
            None,
        )
        return matching or search.data[0]

    async def _resolve_meal_poi(
        self,
        meal: MealDemand,
        command: PlanningCreateCommand,
    ) -> Poi | None:
        trip = command.payload.trip
        for keyword in self._meal_keywords(meal):
            search = await self._map_provider.search_pois(
                PoiSearchRequest(
                    city=trip.destination,
                    keyword=keyword,
                    limit=5,
                )
            )
            if isinstance(search, ProviderFailure):
                continue
            candidates = search.data
            if not candidates:
                continue
            if meal.region:
                regional = tuple(
                    poi for poi in candidates
                    if poi.district and text_matches(meal.region, poi.district)
                )
                if regional:
                    return regional[0]
            return candidates[0]
        return None

    @staticmethod
    def _meal_keywords(meal: MealDemand) -> tuple[str, ...]:
        region = f"{meal.region} 美食" if meal.region else None
        # Only dining-related preferences drive restaurant search; arbitrary
        # preferences (e.g. "历史") must not pull non-restaurant POIs in.
        dining = tuple(
            item.strip()
            for item in meal.preferences
            if item.strip() and any(term in item for term in _DINING_TERMS)
        )
        return tuple(
            dict.fromkeys((*(() if region is None else (region,)), *dining, "美食"))
        )

    async def replan(self, command: PlanningReplanCommand) -> PlanningResult:
        from trip_agent.application.replan_service import (  # noqa: PLC0415
            LocalReplanningProvider,
        )

        return await LocalReplanningProvider(
            self._route_provider,
            self._route_fallback,
            provider_mode=self._provider_mode,
            fallback_policy=self._fallback_policy,
        ).replan(command)

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
                raise PlanningProviderError.from_failure(
                    search,
                    operation=ProviderOperation.POI_SEARCH,
                )
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
                raise PlanningProviderError.from_failure(
                    search,
                    operation=ProviderOperation.POI_SEARCH,
                )
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
                guide_statements=_non_weather_guide_statements(
                    command.payload.guide_evidence.facts
                ),
                entity_facts=_entity_facts_for_pois(tuple(candidates), command),
            )
            if len(ranking.selected) >= required_count:
                return tuple(candidates)
        return tuple(candidates)

    @staticmethod
    def _transit_cost(plan: RoutePlan) -> Decimal | None:
        """Extract monetary cost from a route plan.

        Walking is always free (0).  Driving cost comes from the provider
        (AMap toll estimate) when available; otherwise ``None`` signals
        that the cost could not be determined.
        """
        if plan.mode == "WALKING":
            return Decimal("0.00")
        if plan.estimated_cost is not None:
            return Decimal(str(round(plan.estimated_cost, 2)))
        return None

    @staticmethod
    def _transit_cost_source(
        route: ProviderSuccess[RoutePlan],
    ) -> Literal["PROVIDER", "RULE_ESTIMATE", "DEMO", "UNKNOWN"]:
        if route.provider == "DEMO":
            return "DEMO"
        if route.data.mode == "WALKING":
            return "RULE_ESTIMATE"
        if route.data.estimated_cost is not None:
            return "PROVIDER"
        return "UNKNOWN"

    async def _route(self, request: RouteRequest) -> ProviderSuccess[RoutePlan]:
        result = await self._route_provider.get_route(request)
        fallback_error = None
        if isinstance(result, ProviderFailure):
            primary_error = PlanningProviderError.from_failure(
                result,
                operation=ProviderOperation.ROUTE,
            )
            decision = self._fallback_policy.decide(
                self._provider_mode,
                primary_error.details,
            )
            if (
                decision != FallbackDecision.ALLOW_FALLBACK
                or self._route_fallback is None
            ):
                raise primary_error.with_fallback(
                    allowed=False,
                    attempted=False,
                    succeeded=False,
                )
            logger.warning(
                "provider_route_fallback category=%s reason=%s retry_count=%s",
                primary_error.details.category,
                primary_error.details.error_code,
                primary_error.details.retry_count,
            )
            fallback_error = primary_error.details
            result = await self._route_fallback.get_route(request)
        if isinstance(result, ProviderFailure):
            raise PlanningProviderError.from_failure(
                result,
                operation=ProviderOperation.ROUTE,
            ).with_fallback(allowed=True, attempted=True, succeeded=False)
        if result.provider not in {"AMAP", "DEMO"}:
            raise PlanningProviderError("UNEXPECTED_ROUTE_PROVIDER")
        if (result.provider == "AMAP" and result.estimated) or (
            result.provider == "DEMO" and not result.estimated
        ):
            raise RuntimeError(
                "route provider returned inconsistent source metadata"
            )
        if fallback_error is not None:
            return result.model_copy(update={"fallback_error": fallback_error})
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
