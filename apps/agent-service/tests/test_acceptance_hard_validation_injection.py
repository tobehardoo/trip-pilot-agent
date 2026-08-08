"""CASE 8: Validator failure injection — verify Hard Validation rejects.

Injects duplicate-POI and overlapping-activity itineraries through the
real PlanEvaluator (same code path that guards completion) and asserts
it raises DATA_QUALITY_ERROR instead of returning a high score.
"""
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from plan_evaluation_support import (
    make_activity,
    make_command,
)

from trip_agent.domain.planning.protocols import PlanningResult
from trip_agent.evaluation.evaluator import PlanEvaluator
from trip_agent.providers.errors import PlanningProviderError
from trip_agent.worker.contracts import Itinerary, ItineraryDay


class _FrozenClock:
    @staticmethod
    def now(tz=None):
        return datetime(2026, 8, 1, 12, 0, tzinfo=tz or UTC)


def _as_result(itinerary: Itinerary) -> PlanningResult:
    return PlanningResult(
        provider="AMAP",
        itinerary=itinerary,
        requested_provider_mode="REAL_ONLY",
        primary_provider="AMAP",
        actual_providers=("AMAP",),
        fallback_attempted=False,
        fallback_succeeded=False,
        fallback_reason=None,
        fallback_operations=(),
        guide_fact_ids=(),
    )


def test_duplicate_poi_across_days_blocks_completion() -> None:
    command = make_command()
    first = make_activity(0, source="AMAP")
    repeated = make_activity(1, source="AMAP").model_copy(
        update={"provider_poi_id": first.provider_poi_id}
    )
    itinerary = Itinerary(
        title="Duplicate trip",
        days=(
            ItineraryDay(
                date=command.payload.trip.start_date,
                activities=(first,),
                transit_legs=(),
            ),
            ItineraryDay(
                date=command.payload.trip.start_date + timedelta(days=1),
                activities=(repeated,),
                transit_legs=(),
            ),
        ),
        estimated_total_cost=Decimal("100.00"),
    )

    with pytest.raises(PlanningProviderError, match="duplicate POI") as captured:
        PlanEvaluator(clock=_FrozenClock).evaluate(command, _as_result(itinerary))

    assert captured.value.details.category == "DATA_QUALITY_ERROR"
    assert captured.value.details.retryable is False
    assert captured.value.details.operation == "PLANNING"


def test_overlapping_activities_block_completion() -> None:
    command = make_command()
    first = make_activity(0)
    overlapping = make_activity(1, start_hour=9, start_minute=30)
    itinerary = Itinerary(
        title="Overlapping trip",
        days=(
            ItineraryDay(
                date=command.payload.trip.start_date,
                activities=(first, overlapping),
                transit_legs=(),
            ),
        ),
        estimated_total_cost=Decimal("100.00"),
    )

    with pytest.raises(PlanningProviderError, match="overlap") as captured:
        PlanEvaluator(clock=_FrozenClock).evaluate(command, _as_result(itinerary))

    assert captured.value.details.category == "DATA_QUALITY_ERROR"
    assert captured.value.details.retryable is False


def test_same_structural_kind_is_not_duplicate() -> None:
    """Arrival + departure share kinds but different POIs; not a duplicate."""
    command = make_command()
    arrival = make_activity(0, source="AMAP")
    arrival_poi = arrival.provider_poi_id
    departure = make_activity(1, source="AMAP").model_copy(
        update={"kind": "DEPARTURE", "provider_poi_id": "POI-2"}
    )
    # two activities with different POIs must NOT be flagged
    itinerary = Itinerary(
        title="Clean trip",
        days=(
            ItineraryDay(
                date=command.payload.trip.start_date,
                activities=(arrival, departure),
                transit_legs=(),
            ),
        ),
        estimated_total_cost=Decimal("100.00"),
    )
    assert arrival_poi == "POI-1"
    evaluation = PlanEvaluator(clock=_FrozenClock).evaluate(
        command, _as_result(itinerary)
    )
    assert evaluation.feasible is True
