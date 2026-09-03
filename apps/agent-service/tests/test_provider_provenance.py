import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError
from test_planning_worker import COMMAND

from trip_agent.domain.planning.protocols import PlanningResult
from trip_agent.infrastructure.demo.planning_provider import DemoPlanningProvider
from trip_agent.worker.contracts import (
    ActivityCoordinates,
    FallbackOperation,
    Itinerary,
    ItineraryActivity,
    ItineraryDay,
    PlanningCreateCommand,
    ProviderProvenance,
    TransitLeg,
)
from trip_agent.worker.processor import process_planning_create

ACTIVITY_IDS = tuple(
    UUID(value)
    for value in (
        "4a4c047c-a6dc-41db-b278-4911333f2721",
        "53026baa-f458-489f-9d16-019174f93681",
        "fdd0742a-d8ac-448e-b4ba-f1fef6e36398",
        "fcb270e8-ef2c-45d6-83fc-b8e2084e4216",
    )
)
TRANSIT_IDS = tuple(
    UUID(value)
    for value in (
        "4c627eb2-b3f2-4877-9353-cb3f4a6adf15",
        "abe9fc36-ee33-472e-82c5-7cce8e16148c",
        "ec9f7b06-166c-442c-a70a-d6da202833c6",
    )
)


def _fallback_operation(transit_index: int, error_code: str) -> FallbackOperation:
    return FallbackOperation(
        operation="ROUTE",
        transit_id=TRANSIT_IDS[transit_index],
        from_activity_id=ACTIVITY_IDS[transit_index],
        to_activity_id=ACTIVITY_IDS[transit_index + 1],
        requested_mode="REAL_WITH_EXPLICIT_FALLBACK",
        actual_provider="DEMO",
        error_category="TIMEOUT",
        error_code=error_code,
        retry_count=2,
    )


def _mixed_itinerary() -> Itinerary:
    activities = tuple(
        ItineraryActivity(
            activity_id=activity_id,
            title=f"Activity {index + 1}",
            start_time=datetime(2026, 8, 1, 8 + index * 2, tzinfo=UTC),
            end_time=datetime(2026, 8, 1, 9 + index * 2, tzinfo=UTC),
            estimated_cost=Decimal("0"),
            source="AMAP",
            provider_poi_id=f"POI-{index + 1}",
            coordinates=ActivityCoordinates(longitude=113 + index, latitude=23),
            address=f"Address {index + 1}",
        )
        for index, activity_id in enumerate(ACTIVITY_IDS)
    )
    fallback = _fallback_operation(1, "PROVIDER_TIMEOUT")
    legs = tuple(
        TransitLeg(
            transit_id=transit_id,
            from_activity_index=index,
            to_activity_index=index + 1,
            mode="WALKING",
            distance_meters=100,
            duration_seconds=300,
            provider="DEMO" if index == 1 else "AMAP",
            estimated=index == 1,
            polyline=(ActivityCoordinates(longitude=113 + index, latitude=23),),
            estimated_cost=Decimal("0"),
            cost_source="DEMO" if index == 1 else "RULE_ESTIMATE",
            fallback_operation=fallback if index == 1 else None,
        )
        for index, transit_id in enumerate(TRANSIT_IDS)
    )
    return Itinerary(
        title="Mixed itinerary",
        days=(ItineraryDay(date=date(2026, 8, 1), activities=activities, transit_legs=legs),),
        estimated_total_cost=Decimal("0"),
    )


def test_demo_success_emits_recorded_provenance() -> None:
    command = PlanningCreateCommand.model_validate(COMMAND)

    completed = asyncio.run(process_planning_create(command, DemoPlanningProvider()))

    # B16: demo (UNVERIFIED, no blocker) -> savable v10 completed.
    assert completed.schema_version == 11
    assert completed.event_type == "PLANNING_COMPLETED"
    assert completed.payload.has_blocker is False
    assert completed.payload.provider_provenance == ProviderProvenance(
        requested_provider_mode="DEMO_ONLY",
        primary_provider="DEMO",
        actual_providers=("DEMO",),
        fallback_attempted=False,
        fallback_succeeded=False,
        fallback_reason=None,
        fallback_operations=(),
    )


def test_historical_planning_result_omits_provenance_instead_of_guessing_amap() -> None:
    # _mixed_itinerary() 只生成 1 天（2026-08-01）：command 日期必须与之匹配，
    # 否则会被 AUDIT-02 输出侧 fail-fast 拦截（4 天日期 + 1 天行程 = 非法完成）。
    one_day_command = {
        **COMMAND,
        "payload": {
            **COMMAND["payload"],
            "trip": {
                **COMMAND["payload"]["trip"],
                "startDate": "2026-08-01",
                "endDate": "2026-08-01",
            },
        },
    }
    command = PlanningCreateCommand.model_validate(one_day_command)

    class HistoricalProvider:
        async def plan(self, received: PlanningCreateCommand) -> PlanningResult:
            assert received is command
            return PlanningResult(provider="AMAP", itinerary=_mixed_itinerary())

    completed = asyncio.run(process_planning_create(command, HistoricalProvider()))
    wire = completed.model_dump(mode="json", by_alias=True, exclude_none=True)

    assert "providerProvenance" not in wire["payload"]


def test_mixed_operations_are_deduplicated_and_stably_sorted_at_the_result_boundary() -> None:
    second = _fallback_operation(1, "PROVIDER_TIMEOUT")
    first = _fallback_operation(0, "PROVIDER_UNAVAILABLE")
    result = PlanningResult(
        provider="AMAP",
        itinerary=_mixed_itinerary(),
        requested_provider_mode="REAL_WITH_EXPLICIT_FALLBACK",
        primary_provider="AMAP",
        actual_providers=("DEMO", "AMAP", "DEMO"),
        fallback_attempted=True,
        fallback_succeeded=True,
        fallback_reason="ROUTE_PROVIDER_FAILURE",
        fallback_operations=(second, first, second),
    )

    provenance = result.provider_provenance()

    assert provenance is not None
    assert provenance.actual_providers == ("AMAP", "DEMO")
    assert provenance.fallback_operations == (first, second)


@pytest.mark.parametrize(
    "overrides",
    (
        {"requested_provider_mode": "REAL_ONLY", "actual_providers": ("AMAP", "DEMO")},
        {"requested_provider_mode": "DEMO_ONLY", "actual_providers": ("AMAP",)},
        {"fallback_attempted": False, "fallback_succeeded": True},
        {"fallback_attempted": True, "fallback_succeeded": True, "fallback_operations": ()},
        {"actual_providers": ()},
    ),
)
def test_provider_provenance_rejects_illegal_combinations(overrides: dict[str, object]) -> None:
    values: dict[str, object] = {
        "requested_provider_mode": "REAL_WITH_EXPLICIT_FALLBACK",
        "primary_provider": "AMAP",
        "actual_providers": ("AMAP", "DEMO"),
        "fallback_attempted": True,
        "fallback_succeeded": True,
        "fallback_reason": "ROUTE_PROVIDER_FAILURE",
        "fallback_operations": (_fallback_operation(1, "PROVIDER_TIMEOUT"),),
    }
    values.update(overrides)

    with pytest.raises(ValidationError):
        ProviderProvenance(**values)
