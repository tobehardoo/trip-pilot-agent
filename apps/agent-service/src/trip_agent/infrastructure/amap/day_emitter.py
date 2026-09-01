"""Day emission: a scheduled ``DayPlan`` becomes an ``ItineraryDay``.

``DayEmitter`` projects one deterministic daily plan into the worker-contract
itinerary shape: it resolves per-item costs, turns slots into activities and
transit legs (via ``RouteResolver``), and applies the forward-fit / monotonic
sweep timing corrections.  It is a stateless collaborator of
:class:`~trip_agent.infrastructure.amap.planning_provider.AmapPlanningProvider`.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid5

from trip_agent.domain.planning.protocols import (
    OptimizationConflict,
    PlanningInfeasibleError,
    RelaxationSuggestion,
    ResolvedTravelAnchors,
)
from trip_agent.domain.shared import (
    CHINA_TIME_ZONE,
    coordinate_decimal,
    minute_datetime,
    snapshot_boundary_times,
)
from trip_agent.infrastructure.amap.anchor_resolution import AnchorResolver
from trip_agent.infrastructure.amap.route_resolution import RouteResolver
from trip_agent.planning.context_view import (
    PlanningContextView,
    resolve_transport_strategy_for_date,
    weather_level_for_date,
)
from trip_agent.planning.cost_model import (
    DEFAULT_ACCOMMODATION_PER_NIGHT,
    DEFAULT_MEAL_COST,
    resolve_attraction_cost,
    resolve_meal_cost,
)
from trip_agent.planning.daily_schedule import (
    CandidateActivity,
    DayPlan,
    DayPlanItem,
    FixedSchedule,
    MealWindowConstraint,
    classify_day_type,
)
from trip_agent.planning.decision_trace import DecisionTrace
from trip_agent.planning.transport_strategy import deadline_strategy
from trip_agent.providers.map import Poi, ProviderSuccess
from trip_agent.providers.route import RoutePlan
from trip_agent.worker.contracts import (
    ActivityCoordinates,
    ItineraryActivity,
    ItineraryDay,
    PlanningCreateCommand,
)


class DayEmitter:
    """Daily-plan emission (slots → activities / transit legs)."""

    def __init__(
        self,
        anchor_resolver: AnchorResolver,
        route_resolver: RouteResolver,
    ) -> None:
        self._anchor_resolver = anchor_resolver
        self._route_resolver = route_resolver

    async def emit_day(
        self,
        command: PlanningCreateCommand,
        offset: int,
        day_plan: DayPlan,
        anchors: ResolvedTravelAnchors,
        poi_by_id: dict[str, Poi],
        route_cache: dict[tuple[str, ...], ProviderSuccess[RoutePlan]],
        route_calls: list[int],
        excluded_meal_poi_ids: frozenset[str],
        *,
        decision_traces: list[DecisionTrace] | None = None,
        context_view: PlanningContextView | None = None,
    ) -> tuple[ItineraryDay, Decimal, tuple[str, ...]]:
        trip_date = command.payload.trip.start_date + timedelta(days=offset)
        # V3 P2-0: the resolved context arrives pre-parsed — no per-day
        # re-resolution of weather/budget/strategy inside the emit loop.
        day_context = context_view.days[offset] if context_view is not None else None
        slots: list[dict[str, object]] = []
        unresolved: list[str] = []
        selected_meal_poi_ids = set(excluded_meal_poi_ids)
        # V1 Data-Truth: per-day cost resolution from trusted knowledge facts
        # (TICKET_PRICE / REFERENCE_SPEND) with honest fallback provenance.
        facts = context_view.facts if context_view is not None else ()
        travelers = command.payload.trip.constraints.travelers
        # P1-3: weather × budget × mobility resolved before optimization.
        strategy = (
            day_context.transport_strategy
            if day_context is not None
            else resolve_transport_strategy_for_date(command, trip_date)
        )
        for item in day_plan.items:
            if item.kind == "ARRIVAL" and anchors.arrival is not None:
                slots.append(self.slot_from_item(item, anchors.arrival, trip_date, 0))
            elif item.kind == "DEPARTURE" and anchors.departure is not None:
                slots.append(self.slot_from_item(item, anchors.departure, trip_date, 0))
            elif item.kind == "MEAL" and item.meal is not None:
                restaurant = await self._anchor_resolver.resolve_meal_poi(
                    item.meal,
                    command,
                    excluded_provider_ids=frozenset(selected_meal_poi_ids),
                    decision_traces=decision_traces,
                    context_view=context_view,
                )
                # A meal always happens: an unresolved restaurant is a
                # self-serve meal, not a free one — both carry a real
                # (documented default) estimate with explicit provenance.
                if restaurant is not None:
                    meal_cost = resolve_meal_cost(facts, restaurant.name, travelers=travelers)
                    selected_meal_poi_ids.add(restaurant.provider_id)
                    slots.append(
                        self.slot_from_item(
                            item,
                            restaurant,
                            trip_date,
                            meal_cost.amount,
                            cost_source=meal_cost.source,
                            title=restaurant.name,
                        )
                    )
                else:
                    label = "午餐" if item.meal.meal_type == "LUNCH" else "晚餐"
                    slots.append(
                        self.slot_from_item(
                            item,
                            None,
                            trip_date,
                            DEFAULT_MEAL_COST * max(travelers, 1),
                            cost_source="RULE_ESTIMATE",
                            title=f"{label}（建议在当前区域自行选择餐馆）",
                        )
                    )
                    unresolved.append("MEAL_POI_UNRESOLVED")
            else:
                poi = poi_by_id.get(item.poi_id) if item.poi_id else None
                # Fixed arrangements (place-level schedules) are not recalled
                # with the candidate POIs; resolve their location so the node
                # is a real AMAP activity and transit endpoints stay continuous.
                if poi is None and item.time_fixed and item.kind == "ATTRACTION":
                    poi = await self._anchor_resolver.resolve_fixed_place(item.title, command)
                if item.kind in {"ARRIVAL", "DEPARTURE", "ACCOMMODATION", "MEAL"}:
                    cost, cost_source = Decimal("0"), "UNKNOWN"
                else:
                    # P2-0: candidates (and pinned POIs) already carry their
                    # resolved cost in the view's hints — reuse instead of
                    # re-resolving.  Only non-pool places (fixed arrangements)
                    # resolve live; the inputs are identical, so the value is.
                    hint = (
                        context_view.cost_hints.get(poi.provider_id)
                        if context_view is not None and poi is not None
                        else None
                    )
                    if hint is not None:
                        activity_cost = hint
                    else:
                        activity_cost = resolve_attraction_cost(
                            facts,
                            poi.name if poi is not None else item.title,
                            travelers=travelers,
                        )
                    cost, cost_source = activity_cost.amount, activity_cost.source
                slots.append(
                    self.slot_from_item(item, poi, trip_date, cost, cost_source=cost_source)
                )

        day_count = (command.payload.trip.end_date - command.payload.trip.start_date).days + 1
        if day_count > 1:
            hotel = anchors.accommodation
            start_time = minute_datetime(trip_date, day_plan.window_start_minute)
            end_slot = minute_datetime(trip_date, day_plan.window_end_minute)
            hotel_label = hotel.name if hotel is not None else "住宿地点待确认"
        if day_count > 1 and offset > 0:
            slots.insert(
                0,
                {
                    "title": f"从{hotel_label}出发",
                    "start": start_time - timedelta(minutes=15),
                    "end": start_time,
                    "poi": hotel,
                    "kind": "ACCOMMODATION",
                    "time_fixed": False,
                    "magnitude": None,
                    "cost": Decimal("0"),
                    "cost_source": "UNKNOWN",
                },
            )
        if day_count > 1 and offset < day_count - 1:
            # P1-5: this slot exists exactly once per night, so it carries the
            # night's lodging cost.  A room is shared, so the nightly rate
            # must NOT scale with the party size.
            slots.append(
                {
                    "title": f"返回{hotel_label}",
                    "start": end_slot,
                    "end": end_slot + timedelta(minutes=15),
                    "poi": hotel,
                    "kind": "ACCOMMODATION",
                    "time_fixed": False,
                    "magnitude": None,
                    "cost": DEFAULT_ACCOMMODATION_PER_NIGHT,
                    "cost_source": "CITY_ESTIMATE",
                }
            )

        legs: list[tuple[int, int, ProviderSuccess[RoutePlan]]] = []
        legs_total = len(slots) - 1
        for index in range(legs_total):
            origin = slots[index]
            destination = slots[index + 1]
            origin_poi = origin.get("poi")
            destination_poi = destination.get("poi")
            if origin_poi is None or destination_poi is None:
                continue
            # B19-C: per-leg staged recommendation — a plausible walk still
            # short-circuits to WALKING (B18-B semantics), everything else is
            # compared against real TRANSIT and DRIVING facts.  The remaining
            # leg count feeds the dynamic route-budget reservation so an extra
            # TRANSIT probe never starves later baseline queries.
            route = await self._route_resolver.route_for_pair(
                origin_poi,
                destination_poi,
                origin["end"],
                route_cache,
                route_calls,
                city=command.payload.trip.destination or None,
                remaining_legs=legs_total - index,
                mobility_reduced=command.payload.trip.constraints.mobility_level == "REDUCED",
                # V3 P2-2c: a leg INTO a fixed appointment resolves the
                # conflict "arrival certainty > budget comfort" — the
                # tight-budget widened tolerance must not cost the slot.
                transport_strategy=(
                    deadline_strategy(strategy)
                    if bool(destination.get("time_fixed"))
                    else strategy
                ),
                weather_level=(
                    day_context.weather_level
                    if day_context is not None
                    else weather_level_for_date(command, trip_date)
                ),
                decision_traces=decision_traces,
            )
            # forward-fit: shift the destination and everything after it so the
            # real transit duration fits between activities.
            gap_seconds = (destination["start"] - origin["end"]).total_seconds()
            if gap_seconds < route.data.duration_seconds:
                if bool(destination.get("time_fixed")):
                    raise self.fixed_slot_timing_error(destination)
                shift = timedelta(seconds=route.data.duration_seconds - gap_seconds)
                for later in slots[index + 1 :]:
                    # Flexible work may consume slack before the next fixed
                    # boundary, but it must never move that boundary or any
                    # node on its far side.  A later pair then either fits the
                    # remaining route or fails closed.
                    if bool(later.get("time_fixed")):
                        break
                    later["start"] = later["start"] + shift
                    later["end"] = later["end"] + shift
            legs.append((index, index + 1, route))

        # B13_FIX.2 R12: the forward-fit loop only shifts the destination of
        # each *routed* pair onward.  Pairs that skip routing — unresolved
        # anchors, meals without a resolved POI, accommodation placeholders —
        # never re-check their boundary, so a long route can push a later
        # resolved activity past an intervening placeholder (observed with a
        # real AMap meal POI overlapping the trailing "返回住宿地点待确认"
        # node).  The event consumer rejects such review events and the task
        # stays QUEUED.  A final monotonic sweep restores strict ordering
        # without changing the forward-fit decisions themselves.
        carry = timedelta(0)
        previous_end: datetime | None = None
        for slot in slots:
            if carry and bool(slot.get("time_fixed")):
                raise self.fixed_slot_timing_error(slot)
            slot["start"] = slot["start"] + carry
            slot["end"] = slot["end"] + carry
            if previous_end is not None and slot["start"] < previous_end:
                if bool(slot.get("time_fixed")):
                    raise self.fixed_slot_timing_error(slot)
                carry = previous_end - slot["start"]
                slot["start"] = previous_end
                slot["end"] = slot["end"] + carry
            previous_end = slot["end"]

        activities = tuple(
            self.activity_from_slot(slot, trip_date, command.task_id, index)
            for index, slot in enumerate(slots)
        )
        transit_legs = tuple(
            self._route_resolver.leg_from_route(
                command.task_id,
                trip_date,
                from_index,
                to_index,
                route,
                travelers=command.payload.trip.constraints.travelers,
            )
            for from_index, to_index, route in legs
        )
        # F3: the itinerary total must include activity costs AND every
        # transit leg fare (a TRANSIT ticket is a real monetary cost even
        # though it is never compared against driving tolls across modes).
        total_cost = sum((slot.get("cost") or Decimal("0")) for slot in slots) + sum(
            (leg.estimated_cost or Decimal("0")) for leg in transit_legs
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

    @staticmethod
    def fixed_slot_timing_error(slot: dict[str, object]) -> PlanningInfeasibleError:
        departure = slot.get("kind") == "DEPARTURE"
        return PlanningInfeasibleError(
            conflicts=(
                OptimizationConflict(
                    "INSUFFICIENT_DAY_CAPACITY" if departure else "FIXED_SCHEDULE_OVERLAP",
                    "实际交通时长无法在固定返程时间前完成"
                    if departure
                    else "实际交通时长与固定安排时间冲突",
                    (str(slot.get("title") or ""),),
                ),
            ),
            relaxations=(
                RelaxationSuggestion(
                    "EXTEND_AVAILABLE_TIME" if departure else "CHANGE_FIXED_SCHEDULE",
                    "请提前出发、延后返程时间，或减少前序行程"
                    if departure
                    else "请调整固定安排时间或减少前序行程",
                ),
            ),
        )

    def slot_from_item(
        self,
        item: DayPlanItem,
        poi: Poi | None,
        trip_date: date,
        cost: Decimal,
        *,
        title: str | None = None,
        cost_source: str = "UNKNOWN",
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
            "cost_source": cost_source,
            # B13_FIX R3 (P0-3): MEAL slots carry the explicit meal type so
            # the validation projection can bind by identity.
            "meal_type": item.meal.meal_type if item.meal is not None else None,
        }

    def activity_from_slot(
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
                cost_source=str(slot.get("cost_source") or "UNKNOWN"),  # type: ignore[arg-type]
                source="AMAP",
                provider_poi_id=poi.provider_id,
                coordinates=ActivityCoordinates(
                    longitude=coordinate_decimal(poi.coordinates.longitude),
                    latitude=coordinate_decimal(poi.coordinates.latitude),
                ),
                address=poi.address or poi.name,
                type_code=poi.type_code,
                type_name=poi.type_name,
                kind=kind,  # type: ignore[arg-type]
                time_fixed=time_fixed,
                # B13_FIX R3 (P0-3): MEAL activities carry their explicit
                # meal type in-process for identity binding.
                meal_type=slot.get("meal_type") if kind == "MEAL" else None,
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
            cost_source=str(slot.get("cost_source") or "UNKNOWN"),  # type: ignore[arg-type]
            source="AMAP",
            kind=kind,  # type: ignore[arg-type]
            time_fixed=time_fixed,
            meal_type=slot.get("meal_type") if kind == "MEAL" else None,
        )

    @staticmethod
    def fixed_schedules_on(
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
    def meal_window_constraints(
        constraints: object,
    ) -> tuple[MealWindowConstraint, ...]:
        """Convert worker meal windows into planning-domain constraints.

        BREAKFAST is outside the planning domain (LUNCH/DINNER only) and is
        skipped rather than silently mapped to another meal.  The source
        (B13-F) travels with the constraint so the scheduler can distinguish
        hard USER windows from soft DEFAULT suggestions and DISABLED meals.
        """
        windows = tuple(getattr(constraints, "meal_windows", ()))
        converted: list[MealWindowConstraint] = []
        for window in windows:
            meal_type = getattr(window, "meal_type", None)
            if meal_type not in {"LUNCH", "DINNER"}:
                continue
            start_minute = window.start_time.hour * 60 + window.start_time.minute
            end_minute = window.end_time.hour * 60 + window.end_time.minute
            if end_minute <= start_minute:
                end_minute += 1440
            source = getattr(window, "source", "USER")
            converted.append(MealWindowConstraint(meal_type, start_minute, end_minute, source))
        return tuple(converted)

    @staticmethod
    def special_day_date(
        command: PlanningCreateCommand,
        candidates: tuple[CandidateActivity, ...],
    ) -> date | None:
        if not any(c.magnitude == "FULL_DAY" for c in candidates):
            return None
        trip = command.payload.trip
        arrival_boundary, departure_boundary = snapshot_boundary_times(trip)
        for offset in range((trip.end_date - trip.start_date).days + 1):
            trip_date = trip.start_date + timedelta(days=offset)
            day_type = classify_day_type(
                trip_date,
                trip.start_date,
                trip.end_date,
                arrival_boundary,
                departure_boundary,
            )
            if day_type == "FULL_DAY":
                return trip_date
        return trip.start_date + timedelta(days=1)
