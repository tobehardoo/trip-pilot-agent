"""P2.2–P2.4: the demo itinerary builder and the structural feasibility gate.

The builder turns confirmed slots into a real ``PlanningCreateCommand`` and
runs the demo pipeline — a no-key draft that is a real itinerary object.
Values the wire schema cannot accept fail closed with stable error prefixes;
the structural gate vetoes the reconstructed itinerary object itself.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from trip_agent.agent import (
    ConstraintSlots,
    DemoItineraryBuilder,
    SlotState,
    StructuralFeasibilityGate,
    ToolCall,
    ToolRegistry,
    ToolRuntime,
    build_demo_command,
    normalize_trip_date,
)
from trip_agent.agent.state import AgentState
from trip_agent.domain.planning.protocols import PlanningInfeasibleError
from trip_agent.platform_util import run_async
from trip_agent.worker.contracts import Itinerary, ItineraryActivity, ItineraryDay


def _confirmed_slots(**overrides: object) -> ConstraintSlots:
    slots = (
        ConstraintSlots.empty()
        .fill("destination", "成都", state=SlotState.CONFIRMED)
        .fill("start_date", "2026-10-01", state=SlotState.CONFIRMED)
        .fill("end_date", "2026-10-03", state=SlotState.CONFIRMED)
    )
    for name, value in overrides.items():
        slots = slots.fill(name, value, state=SlotState.CONFIRMED)
    return slots


# ── date normalization ──────────────────────────────────────────────


def test_iso_dates_pass_through() -> None:
    assert normalize_trip_date("2026-10-01") == date(2026, 10, 1)
    assert normalize_trip_date("2026-10-1") == date(2026, 10, 1)


def test_chinese_month_day_resolves_this_year_when_future() -> None:
    today = date(2026, 8, 29)
    assert normalize_trip_date("10月1日", today=today) == date(2026, 10, 1)


def test_chinese_month_day_rolls_to_next_year_once_passed() -> None:
    today = date(2026, 12, 1)
    assert normalize_trip_date("1月1日", today=today) == date(2027, 1, 1)


def test_datetime_and_date_values_pass_through() -> None:
    moment = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
    assert normalize_trip_date(moment) == date(2026, 10, 1)
    assert normalize_trip_date(date(2026, 10, 1)) == date(2026, 10, 1)


def test_unrecognizable_dates_return_none() -> None:
    assert normalize_trip_date("明年春天") is None
    assert normalize_trip_date("2月30日") is None
    assert normalize_trip_date(None) is None


# ── the demo command projection ─────────────────────────────────────


def test_demo_command_round_trips_through_the_wire_schema() -> None:
    command = build_demo_command(
        _confirmed_slots(budget="5000"),
        trip_id="9ee5e831-90f7-4a60-bb8d-fb488aa799ca",
    )
    assert command.schema_version == 2
    assert command.payload.trip.destination == "成都"
    assert command.payload.trip.start_date == date(2026, 10, 1)
    assert command.payload.trip.constraints.budget_amount == Decimal("5000")


def test_missing_destination_fails_closed() -> None:
    slots = ConstraintSlots.empty().fill(
        "start_date", "2026-10-01", state=SlotState.CONFIRMED
    )
    with pytest.raises(ValueError, match="DESTINATION_MISSING"):
        build_demo_command(slots)


def test_unnormalized_dates_fail_closed() -> None:
    with pytest.raises(ValueError, match="UNNORMALIZED_DATE"):
        build_demo_command(_confirmed_slots(start_date="明年春天"))
    with pytest.raises(ValueError, match="UNNORMALIZED_DATE"):
        build_demo_command(_confirmed_slots(end_date="回来再说"))


def test_date_order_and_length_fail_closed() -> None:
    with pytest.raises(ValueError, match="DATE_ORDER"):
        build_demo_command(
            _confirmed_slots(start_date="2026-10-03", end_date="2026-10-01")
        )
    with pytest.raises(ValueError, match="TRIP_TOO_LONG"):
        build_demo_command(_confirmed_slots(end_date="2026-10-20"))


def test_non_numeric_budget_is_dropped_not_guessed() -> None:
    command = build_demo_command(_confirmed_slots(budget="五千"))
    assert command.payload.trip.constraints.budget_amount is None


# ── the demo builder end to end (no keys) ───────────────────────────


def test_demo_builder_produces_a_real_itinerary() -> None:
    builder = DemoItineraryBuilder()
    itinerary = run_async(
        builder(slots=_confirmed_slots(), trip_id="9ee5e831-90f7-4a60-bb8d-fb488aa799ca")
    )
    assert "成都" in itinerary.title
    assert len(itinerary.days) == 3
    assert all(day.activities for day in itinerary.days)


def test_demo_builder_refuses_must_visit_without_real_map_data() -> None:
    builder = DemoItineraryBuilder()
    with pytest.raises(PlanningInfeasibleError):
        run_async(builder(slots=_confirmed_slots(must_visit=["武侯祠"])))


def test_the_tool_maps_infeasibility_to_a_structured_failure() -> None:
    tools = ToolRegistry.with_runtime(ToolRuntime(itinerary_builder=DemoItineraryBuilder()))
    result, _ = run_async(
        tools.invoke(
            ToolCall("build_itinerary"),
            AgentState(slots=_confirmed_slots(must_visit=["武侯祠"])),
        )
    )
    assert not result.ok
    assert result.error_code == "PLANNING_INFEASIBLE"


# ── the structural feasibility gate ─────────────────────────────────


def _itinerary_wire() -> dict:
    start = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
    return Itinerary(
        title="测试行程",
        days=(
            ItineraryDay(
                date=start.date(),
                activities=(
                    ItineraryActivity(
                        title="武侯祠",
                        startTime=start,
                        endTime=start.replace(hour=11),
                        estimatedCost=Decimal("0"),
                        source="DEMO",
                    ),
                ),
                transitLegs=(),
            ),
        ),
        estimatedTotalCost=Decimal("0"),
    ).model_dump(mode="json", by_alias=True, exclude_none=True)


async def _gate_passes_on_a_well_formed_itinerary() -> None:
    gate = StructuralFeasibilityGate()
    report = await gate(itinerary=_itinerary_wire(), slots={})
    assert report.has_blocker is False
    assert "1 days" in report.summary


async def _gate_blocks_an_itinerary_with_no_days() -> None:
    wire = _itinerary_wire()
    wire["days"] = []
    gate = StructuralFeasibilityGate()
    report = await gate(itinerary=wire, slots={})
    # Empty days violate the wire contract itself — reconstruction refuses.
    assert report.has_blocker is True
    assert report.violations


async def _gate_blocks_a_wire_contract_violation() -> None:
    wire = _itinerary_wire()
    wire["days"][0]["activities"][0]["endTime"] = "2026-10-01T08:00:00+00:00"
    gate = StructuralFeasibilityGate()
    report = await gate(itinerary=wire, slots={})
    assert report.has_blocker is True


def test_gate_semantics() -> None:
    run_async(_gate_passes_on_a_well_formed_itinerary())
    run_async(_gate_blocks_an_itinerary_with_no_days())
    run_async(_gate_blocks_a_wire_contract_violation())


def test_the_gate_catches_what_reconstruction_cannot() -> None:
    wire = _itinerary_wire()
    wire["days"][0]["activities"][0]["endTime"] = "2026-10-01T08:00:00+00:00"
    # Reconstruction alone accepts inverted activity times — the semantic
    # check is exactly why the gate exists beyond pydantic.
    Itinerary.model_validate(wire)
    gate = StructuralFeasibilityGate()
    report = run_async(gate(itinerary=wire, slots={}))
    assert report.has_blocker is True
    assert any("ends before it starts" in violation for violation in report.violations)
