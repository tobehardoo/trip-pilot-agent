"""Deterministic planning decisions derived from a frozen trusted context."""

from dataclasses import dataclass
from datetime import date, datetime

from trip_agent.domain.shared import text_matches
from trip_agent.worker.contracts import PlanningContextFact, PlanningContextSnapshot

_OFFICIAL_RELIABILITY = frozenset({"OFFICIAL_ATTRACTION", "OFFICIAL_TOURISM"})
_RAIN_TERMS = ("雨", "雷阵雨", "阵雨", "暴雨", "降水", "rain", "shower")
_INDOOR_TERMS = ("博物馆", "美术馆", "纪念馆", "室内", "museum", "gallery")


@dataclass(frozen=True, slots=True)
class PlanningFactImpact:
    fact_id: str
    category: str
    date: date | None
    effect: str
    target_poi_id: str | None
    target_name: str | None
    reason: str
    source_name: str
    source_type: str
    source_url: str | None
    reliability_level: str
    checked_at: datetime
    evidence: str
    stale: bool
    conflicted: bool
    refresh_failed: bool


def hard_closed_fact(
    context: PlanningContextSnapshot,
    trip_date: date,
    poi_name: str,
) -> PlanningContextFact | None:
    """Return the reviewed, fresh official closure that excludes a POI on a date."""
    return next(
        (
            fact
            for fact in context.facts
            if fact.category == "TEMPORARY_CLOSURE"
            and fact.effective_date == trip_date
            and not fact.stale
            and fact.hard_constraint_eligible
            and fact.source_reviewed
            and fact.reliability_level in _OFFICIAL_RELIABILITY
            and _fact_matches_target(fact, poi_name)
        ),
        None,
    )


def planning_fact_impacts(
    context: PlanningContextSnapshot,
    scheduled_activities: tuple[tuple[date, str], ...],
) -> tuple[PlanningFactImpact, ...]:
    """Explain only facts that can be tied to a rule and an actual trip date."""
    impacts: list[PlanningFactImpact] = []
    for fact in context.facts:
        applicable = tuple(
            (trip_date, target_name)
            for trip_date, target_name in scheduled_activities
            if fact.effective_date is None or fact.effective_date == trip_date
        )
        if not applicable:
            continue
        if fact.stale:
            impacts.append(
                _impact(
                    fact,
                    context=context,
                    date_value=fact.effective_date,
                    effect="STALE_FACT_WARNING",
                    target_name=None,
                    reason="事实已过期，仅作为提示，未形成硬约束",
                )
            )
            continue
        if fact.category == "WEATHER" and _contains_rain(fact):
            for trip_date, target_name in applicable:
                indoor = _contains_any(target_name, _INDOOR_TERMS)
                impacts.append(
                    _impact(
                        fact,
                        context=context,
                        date_value=trip_date,
                        effect=(
                            "INDOOR_POI_UPRANKED"
                            if indoor
                            else "OUTDOOR_POI_DOWNRANKED"
                        ),
                        target_name=target_name,
                        reason=(
                            "对应日期预计降雨，室内候选提高优先级"
                            if indoor
                            else "对应日期预计降雨，露天候选降低优先级"
                        ),
                    )
                )
            continue
        matched = tuple(
            (trip_date, target_name)
            for trip_date, target_name in applicable
            if _fact_matches_target(fact, target_name)
        )
        if fact.category == "TEMPORARY_CLOSURE" and fact.hard_constraint_eligible:
            impacts.append(
                _impact(
                    fact,
                    context=context,
                    date_value=fact.effective_date,
                    effect="OFFICIAL_CLOSURE_APPLIED",
                    target_name=None,
                    reason="新鲜且已审核的官方关闭事实排除了对应日期候选",
                )
            )
        elif fact.category == "RESERVATION_REQUIREMENT":
            impacts.extend(
                _impact(
                    fact,
                    context=context,
                    date_value=trip_date,
                    effect="RESERVATION_REQUIRED",
                    target_name=target_name,
                    reason="行程提示需提前预约",
                )
                for trip_date, target_name in matched
            )
        elif fact.category == "OPENING_HOURS":
            impacts.extend(
                _impact(
                    fact,
                    context=context,
                    date_value=trip_date,
                    effect="OPENING_HOURS_APPLIED",
                    target_name=target_name,
                    reason="活动时间已按开放时间窗核验",
                )
                for trip_date, target_name in matched
            )
        elif fact.category == "TICKET_PRICE":
            impacts.extend(
                _impact(
                    fact,
                    context=context,
                    date_value=trip_date,
                    effect="OFFICIAL_TICKET_BUDGET_APPLIED",
                    target_name=target_name,
                    reason="官方门票价格进入预算估算",
                )
                for trip_date, target_name in matched
            )
        elif fact.reliability_level not in _OFFICIAL_RELIABILITY:
            impacts.extend(
                _impact(
                    fact,
                    context=context,
                    date_value=trip_date,
                    effect="COMMUNITY_GUIDE_SOFT_SIGNAL",
                    target_name=target_name,
                    reason="社区攻略仅作为候选排序与提示信号",
                )
                for trip_date, target_name in matched
            )
    return tuple(impacts)


def _impact(
    fact: PlanningContextFact,
    *,
    context: PlanningContextSnapshot,
    date_value: date | None,
    effect: str,
    target_name: str | None,
    reason: str,
) -> PlanningFactImpact:
    return PlanningFactImpact(
        fact_id=fact.fact_id,
        category=fact.category,
        date=date_value,
        effect=effect,
        target_poi_id=None,
        target_name=target_name,
        reason=reason,
        source_name=fact.source_name,
        source_type=fact.source_type,
        source_url=str(fact.source_url) if fact.source_url is not None else None,
        reliability_level=fact.reliability_level,
        checked_at=fact.checked_at,
        evidence=fact.evidence,
        stale=fact.stale,
        conflicted=any(
            fact.fact_id
            in {
                conflict.selected_fact_id,
                *conflict.conflict_fact_ids,
                *conflict.downgraded_fact_ids,
            }
            for conflict in context.conflicts
        ),
        refresh_failed=any(
            diagnostic.refresh_status in {"PARTIAL", "FAILED"}
            for diagnostic in context.diagnostics
        ),
    )


def _fact_matches_target(fact: PlanningContextFact, target_name: str) -> bool:
    return text_matches(target_name, f"{fact.statement} {fact.evidence}")


def _contains_rain(fact: PlanningContextFact) -> bool:
    return _contains_any(f"{fact.statement} {fact.evidence}", _RAIN_TERMS)


def _contains_any(value: str, terms: tuple[str, ...]) -> bool:
    lowered = value.casefold()
    return any(term.casefold() in lowered for term in terms)
