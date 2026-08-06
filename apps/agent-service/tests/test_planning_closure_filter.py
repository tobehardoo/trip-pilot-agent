"""B8-1: the daily-skeleton path must re-apply hard-closure (TEMPORARY_CLOSURE)
filtering before capacity selection, without silently dropping must-visits."""

import asyncio

import pytest
from test_daily_skeleton_provider import (
    StaticMapProvider,
    SuccessfulRouteProvider,
    _poi,
)

from trip_agent.domain.planning.protocols import PlanningInfeasibleError
from trip_agent.infrastructure.amap.planning_provider import AmapPlanningProvider
from trip_agent.worker.contracts import PlanningCreateCommand


def _closure_command(
    *,
    start: str = "2026-08-01",
    end: str = "2026-08-02",
    closure_date: str | None = "2026-08-01",
    closed_poi: str = "陈家祠",
    must_visit: list[str] | None = None,
    stale: bool = False,
) -> PlanningCreateCommand:
    from test_daily_skeleton_provider import _command

    payload = _command(start=start, end=end).model_dump(by_alias=True)
    payload["schemaVersion"] = 3
    constraints = payload["payload"]["trip"]["constraints"]
    if must_visit is not None:
        constraints["mustVisitPlaces"] = must_visit
    fact = {
        "factId": "closure-fact-0123456789abcdef",
        "category": "TEMPORARY_CLOSURE",
        "statement": f"{closed_poi} 临时闭馆",
        "normalizedValue": {"closed": True},
        "evidence": f"官方通知：{closed_poi} 当日闭馆",
        "effectiveDate": closure_date,
        "checkedAt": "2026-07-13T08:00:00Z",
        "expiresAt": "2026-08-10T08:00:00Z",
        "stale": stale,
        "sourceName": closed_poi,
        "sourceType": "OFFICIAL_ATTRACTION",
        "sourceUrl": "https://example.com/closure",
        "reliabilityLevel": "OFFICIAL_ATTRACTION",
        "sourceReviewed": True,
        "hardConstraintEligible": not stale,
    }
    payload["payload"]["planningContext"] = {
        "snapshotId": "67396263-bac9-4db8-bc4c-08d57493ba26",
        "schemaVersion": 3,
        "tripId": payload["tripId"],
        "planningTaskId": payload["taskId"],
        "city": "广州",
        "travelStartDate": start,
        "travelEndDate": end,
        "generatedAt": "2026-07-13T08:00:00Z",
        "stale": stale,
        "sources": [
            {
                "sourceName": closed_poi,
                "sourceType": "OFFICIAL_ATTRACTION",
                "sourceUrl": "https://example.com/closure",
                "reliabilityLevel": "OFFICIAL_ATTRACTION",
            }
        ],
        "facts": [fact],
        "conflicts": [],
        "excludedFacts": [],
        "diagnostics": [],
    }
    return PlanningCreateCommand.model_validate(payload)


def _provider(pois: tuple) -> AmapPlanningProvider:
    return AmapPlanningProvider(
        StaticMapProvider(pois),
        SuccessfulRouteProvider(),
    )


def _titles(day) -> set[str]:
    return {a.title for a in day.activities}


def test_closed_candidate_is_excluded_from_that_day() -> None:
    # Single-day trip; 陈家祠 is the only candidate and is closed that day.
    command = _closure_command(
        start="2026-08-01",
        end="2026-08-01",
        closure_date="2026-08-01",
        closed_poi="陈家祠",
    )
    result = asyncio.run(_provider((_poi("chen", "陈家祠"),)).plan(command))
    titles = _titles(result.itinerary.days[0])
    assert "陈家祠" not in titles
    # The day is still valid (meal time preserved).
    assert any(kind == "MEAL" for kind in [a.kind for a in result.itinerary.days[0].activities])


def test_must_visit_closed_returns_explicit_infeasible() -> None:
    command = _closure_command(
        start="2026-08-01",
        end="2026-08-01",
        closure_date="2026-08-01",
        closed_poi="陈家祠",
        must_visit=["陈家祠"],
    )
    with pytest.raises(PlanningInfeasibleError) as failure:
        asyncio.run(_provider((_poi("chen", "陈家祠"),)).plan(command))

    assert failure.value.conflicts[0].code == "MUST_VISIT_UNAVAILABLE"
    assert "临时关闭" in failure.value.conflicts[0].message
    assert "陈家祠" in failure.value.conflicts[0].affected
    assert failure.value.relaxations


def test_must_visit_closed_on_one_day_can_be_rescheduled() -> None:
    # Closed only on day 1; the must-visit can move to day 2.
    command = _closure_command(
        closure_date="2026-08-01",
        closed_poi="陈家祠",
        must_visit=["陈家祠"],
    )
    result = asyncio.run(
        _provider((_poi("chen", "陈家祠"), _poi("park", "越秀公园"))).plan(command)
    )
    assert any("陈家祠" in _titles(day) for day in result.itinerary.days)


def test_stale_historical_closure_does_not_filter() -> None:
    # A stale (historical) closure fact must not remove the candidate.
    command = _closure_command(
        start="2026-08-01",
        end="2026-08-01",
        closure_date="2026-08-01",
        closed_poi="陈家祠",
        must_visit=["陈家祠"],
        stale=True,
    )
    result = asyncio.run(_provider((_poi("chen", "陈家祠"),)).plan(command))
    assert "陈家祠" in _titles(result.itinerary.days[0])


def test_candidates_not_matching_closure_fact_are_unaffected() -> None:
    # Closure targets 陈家祠; 广州塔 is untouched and still scheduled.
    command = _closure_command(
        start="2026-08-01",
        end="2026-08-01",
        closure_date="2026-08-01",
        closed_poi="陈家祠",
    )
    result = asyncio.run(_provider((_poi("tower", "广州塔"),)).plan(command))
    assert "广州塔" in _titles(result.itinerary.days[0])
