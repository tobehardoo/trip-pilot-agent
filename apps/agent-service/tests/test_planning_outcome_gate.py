"""AUDIT-02 防回归：Planner 输出侧 fail-fast（_assert_plannable_outcome）。

任何进入 COMPLETED 的行程必须：itinerary 非空、days>0、天数==(end-start)+1、
每一天≥1 活动。否则必须抛 PlanningInfeasibleError（AMQP 层转 PLANNING_FAILED），
绝不发出结构非法的 PlanningCompletedEventV11。

Case 1: 4 天旅行, 0 days → FAIL
Case 2: 4 天旅行, 1 day  → FAIL
Case 3: 4 天旅行, 4 days, 每天≥1 activity → PASS
Case 4: days=[] → FAIL
Case 5: itinerary=None → FAIL
"""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from trip_agent.domain.planning.protocols import PlanningInfeasibleError, PlanningResult
from trip_agent.worker.contracts import (
    Itinerary,
    ItineraryActivity,
    ItineraryDay,
    PlanningCreateCommand,
)
from trip_agent.worker.processor import _assert_plannable_outcome

START_DATE = "2026-08-01"
END_DATE = "2026-08-04"  # 4 天（含首尾）

COMMAND = {
    "eventType": "PLANNING_CREATE_REQUESTED",
    "schemaVersion": 1,
    "eventId": "08db18af-3dfe-4e3f-9e3e-2900d43385b4",
    "traceId": "8f5ef9c2-c194-4292-b847-5b9dcfda978b",
    "taskId": "b0642d34-e24f-4b24-9ea7-82a68a4be781",
    "tripId": "08be9aca-fb30-4309-aa4b-93c240f19d75",
    "occurredAt": "2026-07-14T03:00:00Z",
    "payload": {
        "taskType": "CREATE",
        "baselineTripVersion": 0,
        "idempotencyKey": "d05b381a-39af-47b5-9925-52f412629f8f",
        "trip": {
            "title": "成都四日",
            "destination": "成都",
            "startDate": START_DATE,
            "endDate": END_DATE,
            "status": "DRAFT",
            "version": 0,
            "constraints": {
                "budgetAmount": 2500.00,
                "travelers": 1,
                "travelerType": "SOLO",
                "pace": "RELAXED",
                "preferences": [],
                "fixedSchedules": [],
                "schemaVersion": 1,
            },
        },
    },
}


def _command() -> PlanningCreateCommand:
    return PlanningCreateCommand.model_validate(COMMAND)


def _itinerary(day_count: int, activities_per_day: int = 1) -> Itinerary:
    start = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)
    days = tuple(
        ItineraryDay(
            date=start.date() + timedelta(days=index),
            activities=tuple(
                ItineraryActivity(
                    title=f"活动{index}-{activity_index}",
                    startTime=start,
                    endTime=start.replace(hour=11),
                    estimatedCost=Decimal("0"),
                    source="DEMO",
                )
                for activity_index in range(activities_per_day)
            ),
            transitLegs=(),
        )
        for index in range(day_count)
    )
    return Itinerary(title="成都四日", days=days, estimatedTotalCost=Decimal("0"))


def _result(itinerary: Itinerary | None) -> PlanningResult:
    if itinerary is None:
        # itinerary=None 场景需绕过 dataclass 必填：用 replace 注入 None。
        base = PlanningResult(provider="DEMO", itinerary=_itinerary(4))
        return replace(base, itinerary=None)
    return PlanningResult(provider="DEMO", itinerary=itinerary)


def test_case_1_four_days_zero_days_generated_fails() -> None:
    # 契约层（days min_length=1）已拒绝 0 天构造；这里直接验证 Gate 分支。
    # 通过 raw pydantic 构造 0 天对象（绕过校验）等价于契约漏洞被 Gate 兜住。
    raw = Itinerary.model_construct(
        title="成都四日", days=(), estimated_total_cost=Decimal("0")
    )
    with pytest.raises(PlanningInfeasibleError) as exc:
        _assert_plannable_outcome(_command(), _result(raw))
    assert "zero days" in str(exc.value)


def test_case_2_four_days_one_day_generated_fails() -> None:
    with pytest.raises(PlanningInfeasibleError) as exc:
        _assert_plannable_outcome(_command(), _result(_itinerary(1)))
    assert "day count 1 != expected 4" in str(exc.value)


def test_case_3_four_days_four_days_with_activities_passes() -> None:
    # 4 天、每天≥1 活动 → 通过，不抛异常。
    _assert_plannable_outcome(_command(), _result(_itinerary(4, activities_per_day=1)))


def test_case_4_empty_days_fails() -> None:
    raw = Itinerary.model_construct(
        title="成都四日", days=(), estimated_total_cost=Decimal("0")
    )
    with pytest.raises(PlanningInfeasibleError) as exc:
        _assert_plannable_outcome(_command(), _result(raw))
    assert "zero days" in str(exc.value)


def test_case_5_none_itinerary_fails() -> None:
    with pytest.raises(PlanningInfeasibleError) as exc:
        _assert_plannable_outcome(_command(), _result(None))
    assert "itinerary=None" in str(exc.value)


def test_case_3b_a_day_without_activities_fails() -> None:
    # 天数匹配但某一天 0 活动 → 仍必须 FAIL（契约层 activity min_length 拒绝，
    # 这里用 model_construct 绕过以覆盖 Gate 分支）。
    start = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)
    day = ItineraryDay.model_construct(
        date=start.date(), activities=(), transit_legs=()
    )
    raw = Itinerary.model_construct(
        title="成都四日",
        days=(day,) * 4,
        estimated_total_cost=Decimal("0"),
    )
    with pytest.raises(PlanningInfeasibleError) as exc:
        _assert_plannable_outcome(_command(), _result(raw))
    assert "contains no activities" in str(exc.value)