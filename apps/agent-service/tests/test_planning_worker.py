from copy import deepcopy
from importlib import import_module

import pytest
from pydantic import ValidationError

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
            "title": "广州四日慢游",
            "destination": "广州",
            "startDate": "2026-08-01",
            "endDate": "2026-08-04",
            "status": "DRAFT",
            "version": 0,
            "constraints": {
                "budgetAmount": 6000.00,
                "travelers": 2,
                "travelerType": "FRIENDS",
                "pace": "BALANCED",
                "preferences": ["美食", "历史"],
                "fixedSchedules": [],
                "schemaVersion": 1,
            },
        },
    },
}


def test_contract_parses_java_command_and_rejects_unknown_fields() -> None:
    contracts = import_module("trip_agent.worker.contracts")
    command_type = getattr(contracts, "PlanningCreateCommand", None)
    assert command_type is not None

    command = command_type.model_validate(COMMAND)

    assert str(command.task_id) == COMMAND["taskId"]
    assert command.payload.trip.destination == "广州"
    assert command.payload.trip.constraints.budget_amount == 6000
    with pytest.raises(ValidationError):
        command_type.model_validate({**COMMAND, "unexpected": True})


@pytest.mark.parametrize("travelers", [0, 51])
def test_contract_rejects_out_of_range_traveler_counts(travelers: int) -> None:
    contracts = import_module("trip_agent.worker.contracts")
    command_type = contracts.PlanningCreateCommand
    invalid = deepcopy(COMMAND)
    invalid["payload"]["trip"]["constraints"]["travelers"] = travelers

    with pytest.raises(ValidationError):
        command_type.model_validate(invalid)


def test_contract_rejects_schema_incompatible_coercions_and_empty_strings() -> None:
    contracts = import_module("trip_agent.worker.contracts")
    command_type = contracts.PlanningCreateCommand
    coerced_travelers = deepcopy(COMMAND)
    coerced_travelers["payload"]["trip"]["constraints"]["travelers"] = "2"
    coerced_budget = deepcopy(COMMAND)
    coerced_budget["payload"]["trip"]["constraints"]["budgetAmount"] = "6000"
    coerced_version = deepcopy(COMMAND)
    coerced_version["payload"]["trip"]["version"] = "0"
    empty_title = deepcopy(COMMAND)
    empty_title["payload"]["trip"]["title"] = ""

    for invalid in (coerced_travelers, coerced_budget, coerced_version, empty_title):
        with pytest.raises(ValidationError):
            command_type.model_validate(invalid)


def test_contract_rejects_internal_field_names_on_the_wire() -> None:
    contracts = import_module("trip_agent.worker.contracts")
    command_type = contracts.PlanningCreateCommand
    snake_case = deepcopy(COMMAND)
    snake_case["event_type"] = snake_case.pop("eventType")

    with pytest.raises(ValidationError):
        command_type.model_validate(snake_case)


def test_contract_rejects_mismatched_baseline_trip_version() -> None:
    contracts = import_module("trip_agent.worker.contracts")
    command_type = contracts.PlanningCreateCommand
    mismatched = deepcopy(COMMAND)
    mismatched["payload"]["baselineTripVersion"] = 99

    with pytest.raises(ValidationError):
        command_type.model_validate(mismatched)


def test_contract_enforces_committed_string_limits() -> None:
    contracts = import_module("trip_agent.worker.contracts")
    command_type = contracts.PlanningCreateCommand
    long_title = deepcopy(COMMAND)
    long_title["payload"]["trip"]["title"] = "x" * 121
    long_preference = deepcopy(COMMAND)
    long_preference["payload"]["trip"]["constraints"]["preferences"] = ["x" * 61]
    long_place = deepcopy(COMMAND)
    long_place["payload"]["trip"]["constraints"]["fixedSchedules"] = [
        {
            "placeName": "x" * 121,
            "startTime": "2026-08-02T19:00:00+08:00",
            "endTime": "2026-08-02T21:00:00+08:00",
        }
    ]

    for invalid in (long_title, long_preference, long_place):
        with pytest.raises(ValidationError):
            command_type.model_validate(invalid)


def test_contract_rejects_reversed_trip_dates_and_fixed_schedules() -> None:
    contracts = import_module("trip_agent.worker.contracts")
    command_type = contracts.PlanningCreateCommand
    reversed_trip = deepcopy(COMMAND)
    reversed_trip["payload"]["trip"]["endDate"] = "2026-07-31"
    reversed_schedule = deepcopy(COMMAND)
    reversed_schedule["payload"]["trip"]["constraints"]["fixedSchedules"] = [
        {
            "placeName": "广州塔",
            "startTime": "2026-08-02T21:00:00+08:00",
            "endTime": "2026-08-02T19:00:00+08:00",
        }
    ]

    with pytest.raises(ValidationError):
        command_type.model_validate(reversed_trip)
    with pytest.raises(ValidationError):
        command_type.model_validate(reversed_schedule)


def test_demo_processor_emits_a_deterministic_completed_event() -> None:
    contracts = import_module("trip_agent.worker.contracts")
    processor = import_module("trip_agent.worker.processor")
    command_type = getattr(contracts, "PlanningCreateCommand", None)
    provider_type = getattr(processor, "DemoPlanningProvider", None)
    process = getattr(processor, "process_planning_create", None)
    assert command_type is not None
    assert provider_type is not None
    assert process is not None
    command = command_type.model_validate(COMMAND)

    first = process(command, provider_type())
    repeated = process(command, provider_type())

    assert first.event_type == "PLANNING_COMPLETED"
    assert first.event_id == repeated.event_id
    assert first.run_id == repeated.run_id
    assert first.trace_id == command.trace_id
    assert first.task_id == command.task_id
    assert first.trip_id == command.trip_id
    assert first.payload.provider == "DEMO"


def test_demo_provider_builds_one_explicitly_sourced_day_per_trip_date() -> None:
    contracts = import_module("trip_agent.worker.contracts")
    processor = import_module("trip_agent.worker.processor")
    command_type = getattr(contracts, "PlanningCreateCommand", None)
    provider_type = getattr(processor, "DemoPlanningProvider", None)
    process = getattr(processor, "process_planning_create", None)
    assert command_type is not None
    assert provider_type is not None
    assert process is not None
    command = command_type.model_validate(COMMAND)

    completed = process(command, provider_type())

    assert [str(day.date) for day in completed.payload.itinerary.days] == [
        "2026-08-01",
        "2026-08-02",
        "2026-08-03",
        "2026-08-04",
    ]
    assert all(len(day.activities) == 1 for day in completed.payload.itinerary.days)
    assert all(day.activities[0].source == "DEMO" for day in completed.payload.itinerary.days)
    assert completed.payload.itinerary.estimated_total_cost == 0


@pytest.mark.parametrize("invalid_cost", ["0.001", "10000000000.00"])
def test_completed_event_models_reject_unpersistable_money(invalid_cost: str) -> None:
    contracts = import_module("trip_agent.worker.contracts")

    with pytest.raises(ValidationError):
        contracts.DemoItinerary.model_validate(
            {
                "title": "Demo itinerary",
                "days": [
                    {
                        "date": "2026-08-01",
                        "activities": [
                            {
                                "title": "Demo activity",
                                "startTime": "2026-08-01T09:00:00+08:00",
                                "endTime": "2026-08-01T10:00:00+08:00",
                                "estimatedCost": invalid_cost,
                                "source": "DEMO",
                            }
                        ],
                    }
                ],
                "estimatedTotalCost": invalid_cost,
            }
        )


def test_completed_event_models_reject_titles_over_two_hundred_characters() -> None:
    contracts = import_module("trip_agent.worker.contracts")

    with pytest.raises(ValidationError):
        contracts.DemoItinerary.model_validate(
            {
                "title": "x" * 201,
                "days": [
                    {
                        "date": "2026-08-01",
                        "activities": [
                            {
                                "title": "Demo activity",
                                "startTime": "2026-08-01T09:00:00+08:00",
                                "endTime": "2026-08-01T10:00:00+08:00",
                                "estimatedCost": 0,
                                "source": "DEMO",
                            }
                        ],
                    }
                ],
                "estimatedTotalCost": 0,
            }
        )
