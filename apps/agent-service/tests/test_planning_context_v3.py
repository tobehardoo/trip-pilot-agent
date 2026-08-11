import asyncio
from copy import deepcopy
from datetime import date

from test_planning_context_v2 import _v2_command

from trip_agent.planning.trusted_context import (
    hard_closed_fact,
    planning_fact_impacts,
)
from trip_agent.worker.contracts import PlanningCreateCommand
from trip_agent.worker.processor import DemoPlanningProvider, process_planning_create


def _v3_command() -> dict:
    payload = deepcopy(_v2_command())
    payload["schemaVersion"] = 3
    payload["payload"]["planningContext"] = {
        "snapshotId": "67396263-bac9-4db8-bc4c-08d57493ba26",
        "schemaVersion": 3,
        "tripId": payload["tripId"],
        "planningTaskId": payload["taskId"],
        "city": "广州",
        "travelStartDate": "2026-08-01",
        "travelEndDate": "2026-08-02",
        "generatedAt": "2026-07-13T08:00:00Z",
        "stale": True,
        "sources": [
            {
                "sourceName": "广州博物馆",
                "sourceType": "OFFICIAL_ATTRACTION",
                "sourceUrl": "https://www.guangzhoumuseum.cn/",
                "reliabilityLevel": "OFFICIAL_ATTRACTION",
            }
        ],
        "facts": [
            {
                "factId": "fact_0123456789abcdef0123456789abcdef",
                "category": "TEMPORARY_CLOSURE",
                "statement": "广州博物馆 8 月 1 日临时闭馆",
                "normalizedValue": {"closed": True},
                "evidence": "8 月 1 日临时闭馆",
                "effectiveDate": "2026-08-01",
                "checkedAt": "2026-07-12T08:00:00Z",
                "expiresAt": "2026-07-13T07:00:00Z",
                "stale": True,
                "sourceName": "广州博物馆",
                "sourceType": "OFFICIAL_ATTRACTION",
                "sourceUrl": "https://www.guangzhoumuseum.cn/",
                "reliabilityLevel": "OFFICIAL_ATTRACTION",
                "sourceReviewed": True,
                "hardConstraintEligible": False,
            }
        ],
        "conflicts": [],
        "excludedFacts": [],
        "diagnostics": [
            {
                "code": "CITY_INTELLIGENCE_PROVIDER_FAILED",
                "message": "provider unavailable",
                "refreshStatus": "FAILED",
            }
        ],
    }
    return payload


def test_v3_accepts_an_immutable_stale_context_without_promoting_it_to_a_hard_rule() -> None:
    command = PlanningCreateCommand.model_validate(_v3_command())

    context = command.payload.planning_context
    assert context is not None
    assert context.schema_version == 3
    assert context.facts[0].effective_date == date(2026, 8, 1)
    assert context.facts[0].stale is True
    assert context.facts[0].hard_constraint_eligible is False


def test_v3_accepts_nested_normalized_values_from_the_strict_model_contract() -> None:
    payload = _v3_command()
    payload["payload"]["planningContext"]["facts"][0]["normalizedValue"] = {
        "weeklyHours": [
            {"days": ["MONDAY", "TUESDAY"], "open": "09:00", "close": "17:00"}
        ],
        "reservation": {"required": True, "channels": ["官网", "小程序"]},
    }

    command = PlanningCreateCommand.model_validate(payload)

    context = command.payload.planning_context
    assert context is not None
    assert context.facts[0].normalized_value is not None
    assert context.facts[0].normalized_value["reservation"] == {
        "required": True,
        "channels": ["官网", "小程序"],
    }


def test_v3_requires_snapshot_and_command_identity_to_match() -> None:
    payload = _v3_command()
    payload["payload"]["trip"]["constraints"]["mustVisitPlaces"] = []
    payload["payload"]["planningContext"]["planningTaskId"] = (
        "4bc34f7a-82f7-42bc-a3ef-694c28c845fc"
    )

    try:
        PlanningCreateCommand.model_validate(payload)
    except ValueError as exception:
        assert "planning context identity" in str(exception)
    else:
        raise AssertionError("mismatched planning context identity was accepted")


def test_only_fresh_reviewed_official_closure_forms_a_date_scoped_hard_rule() -> None:
    payload = _v3_command()
    fact = payload["payload"]["planningContext"]["facts"][0]
    fact["stale"] = False
    fact["hardConstraintEligible"] = True
    fact["expiresAt"] = "2026-08-03T08:00:00Z"
    payload["payload"]["planningContext"]["stale"] = False
    command = PlanningCreateCommand.model_validate(payload)
    context = command.payload.planning_context
    assert context is not None

    assert hard_closed_fact(context, date(2026, 8, 1), "广州博物馆") is not None
    assert hard_closed_fact(context, date(2026, 8, 2), "广州博物馆") is None

    community = context.facts[0].model_copy(
        update={
            "source_reviewed": False,
            "reliability_level": "COMMUNITY",
            "hard_constraint_eligible": False,
        }
    )
    context = context.model_copy(update={"facts": (community,)})
    assert hard_closed_fact(context, date(2026, 8, 1), "广州博物馆") is None


def test_fact_impacts_are_scoped_to_the_actual_activity_date() -> None:
    payload = _v3_command()
    fact = payload["payload"]["planningContext"]["facts"][0]
    fact.update(
        {
            "category": "WEATHER",
            "statement": "8 月 1 日预计有雨",
            "evidence": "预计有雨",
            "hardConstraintEligible": False,
        }
    )
    payload["payload"]["planningContext"]["conflicts"] = [
        {
            "selectedFactId": fact["factId"],
            "conflictFactIds": ["fact_conflicting_1234567890"],
            "downgradedFactIds": ["fact_conflicting_1234567890"],
            "reason": "官方天气优先于旧攻略",
            "needsManualReview": False,
        }
    ]
    command = PlanningCreateCommand.model_validate(payload)
    context = command.payload.planning_context
    assert context is not None

    impacts = planning_fact_impacts(
        context,
        (
            (date(2026, 8, 1), "越秀公园"),
            (date(2026, 8, 2), "上海博物馆"),
        ),
    )

    assert len(impacts) == 1
    assert impacts[0].date == date(2026, 8, 1)
    assert impacts[0].effect == "STALE_FACT_WARNING"


def test_opening_hours_fact_produces_neutral_evidence_impact_only() -> None:
    """B1-F: merely having an opening-hours fact must not claim the activity
    time window was verified.  Expected: OPENING_HOURS_EVIDENCE_AVAILABLE
    with a neutral reason; never OPENING_HOURS_APPLIED."""
    payload = _v3_command()
    payload["payload"]["trip"]["constraints"]["mustVisitPlaces"] = []
    payload["payload"]["planningContext"]["facts"] = [
        {
            "factId": "fact_opening_0123456789abcdef",
            "category": "OPENING_HOURS",
            "statement": "广州博物馆开放时间：09:00-17:00",
            "normalizedValue": {
                "scope": "DAILY",
                "openingWindows": [
                    {"open": "09:00", "close": "17:00", "closeDayOffset": 0}
                ],
                "raw": "开放时间：09:00-17:00",
            },
            "evidence": "09:00-17:00",
            "effectiveDate": None,
            "checkedAt": "2026-07-13T08:00:00Z",
            "expiresAt": "2026-08-10T08:00:00Z",
            "stale": False,
            "sourceName": "广州博物馆",
            "sourceType": "OFFICIAL_ATTRACTION",
            "sourceUrl": "https://www.guangzhoumuseum.cn/",
            "reliabilityLevel": "OFFICIAL_ATTRACTION",
            "sourceReviewed": True,
            "hardConstraintEligible": True,
        }
    ]
    payload["payload"]["planningContext"]["stale"] = False
    command = PlanningCreateCommand.model_validate(payload)
    context = command.payload.planning_context
    assert context is not None

    impacts = planning_fact_impacts(
        context,
        (
            (date(2026, 8, 1), "广州博物馆"),
            (date(2026, 8, 2), "上海博物馆"),
        ),
    )

    assert len(impacts) == 1
    assert impacts[0].effect == "OPENING_HOURS_EVIDENCE_AVAILABLE"
    assert impacts[0].reason == "已关联营业时间证据，尚未完成活动时间窗验证"
    assert all(
        impact.effect != "OPENING_HOURS_APPLIED"
        and "已按开放时间窗核验" not in impact.reason
        for impact in impacts
    )


def test_reservation_fact_impact_semantics_are_unchanged() -> None:
    """B1-F: other trusted-fact impacts keep their existing semantics."""
    payload = _v3_command()
    payload["payload"]["trip"]["constraints"]["mustVisitPlaces"] = []
    payload["payload"]["planningContext"]["facts"] = [
        {
            "factId": "fact_reservation_0123456789abcd",
            "category": "RESERVATION_REQUIREMENT",
            "statement": "广州博物馆需要提前预约",
            "normalizedValue": {"required": True},
            "evidence": "需要提前预约",
            "effectiveDate": None,
            "checkedAt": "2026-07-13T08:00:00Z",
            "expiresAt": "2026-08-10T08:00:00Z",
            "stale": False,
            "sourceName": "广州博物馆",
            "sourceType": "OFFICIAL_ATTRACTION",
            "sourceUrl": "https://www.guangzhoumuseum.cn/",
            "reliabilityLevel": "OFFICIAL_ATTRACTION",
            "sourceReviewed": True,
            "hardConstraintEligible": True,
        }
    ]
    payload["payload"]["planningContext"]["stale"] = False
    command = PlanningCreateCommand.model_validate(payload)
    context = command.payload.planning_context
    assert context is not None

    impacts = planning_fact_impacts(
        context,
        ((date(2026, 8, 1), "广州博物馆"),),
    )

    assert len(impacts) == 1
    assert impacts[0].effect == "RESERVATION_REQUIRED"


def test_completed_v6_event_exposes_fact_impacts_from_the_frozen_snapshot() -> None:
    payload = _v3_command()
    payload["payload"]["trip"]["constraints"]["mustVisitPlaces"] = []
    fact = payload["payload"]["planningContext"]["facts"][0]
    fact.update(
        {
            "category": "WEATHER",
            "statement": "8 月 1 日预计有雨",
            "evidence": "预计有雨",
        }
    )
    payload["payload"]["planningContext"]["conflicts"] = [
        {
            "selectedFactId": fact["factId"],
            "conflictFactIds": ["fact_conflicting_1234567890"],
            "downgradedFactIds": ["fact_conflicting_1234567890"],
            "reason": "官方天气优先于旧攻略",
            "needsManualReview": False,
        }
    ]
    command = PlanningCreateCommand.model_validate(payload)

    completed = asyncio.run(process_planning_create(command, DemoPlanningProvider()))
    wire = completed.model_dump(mode="json", by_alias=True, exclude_none=True)

    assert wire["schemaVersion"] == 1
    assert wire["eventType"] == "PLANNING_REVIEW_REQUIRED"
    assert wire["payload"]["factImpacts"][0]["factId"] == fact["factId"]
    assert wire["payload"]["factImpacts"][0]["effect"] == "STALE_FACT_WARNING"
    assert wire["payload"]["factImpacts"][0]["evidence"] == "预计有雨"
    assert wire["payload"]["factImpacts"][0]["sourceType"] == "OFFICIAL_ATTRACTION"
    assert wire["payload"]["factImpacts"][0]["sourceUrl"].startswith("https://")
    assert wire["payload"]["factImpacts"][0]["conflicted"] is True
    assert wire["payload"]["factImpacts"][0]["refreshFailed"] is True
