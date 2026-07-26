import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from jsonschema import Draft202012Validator

from trip_agent.worker.contracts import (
    PlanningConflict,
    PlanningFailedEvent,
    PlanningFailedPayload,
    PlanningRelaxation,
)

CONTRACT_DIRECTORY = Path(__file__).parents[3] / "contracts" / "messaging"
ACTIVE_SCHEMA_FILES = (
    "planning-cancel-command-v1.schema.json",
    "planning-completed-event-v4.schema.json",
    "planning-completed-event-v5.schema.json",
    "planning-create-command-v2.schema.json",
    "planning-failed-event-v1.schema.json",
    "planning-replan-command-v1.schema.json",
)


def _load_schema(file_name: str) -> dict[str, object]:
    with (CONTRACT_DIRECTORY / file_name).open(encoding="utf-8") as schema_file:
        return json.load(schema_file)


def test_every_active_messaging_schema_is_a_valid_draft_2020_12_schema() -> None:
    for file_name in ACTIVE_SCHEMA_FILES:
        Draft202012Validator.check_schema(_load_schema(file_name))


def test_planning_failed_event_model_matches_its_json_schema() -> None:
    event = PlanningFailedEvent(
        event_type="PLANNING_FAILED",
        schema_version=1,
        event_id=UUID("38e10d2b-fd84-55ae-97dc-a1e00cac682b"),
        trace_id=UUID("ea930620-41a7-4fdc-b6d1-d298a850112a"),
        task_id=UUID("dfb858fc-b910-4056-a375-2366dcaab690"),
        trip_id=UUID("d209daf2-f004-42cc-8385-510825f40fe1"),
        run_id=UUID("3b85b6b6-9e42-433b-90ef-d94a3eb26e18"),
        occurred_at=datetime(2026, 7, 26, 8, 0, tzinfo=UTC),
        payload=PlanningFailedPayload(
            status="FAILED",
            error_code="NO_FEASIBLE_ITINERARY",
            message="时间、交通与固定安排无法同时满足",
            conflicts=(
                PlanningConflict(
                    code="INSUFFICIENT_DAY_CAPACITY",
                    message="当天可用时间不足",
                    affected=("2026-08-01",),
                ),
            ),
            relaxation_suggestions=(
                PlanningRelaxation(
                    code="REDUCE_OPTIONAL_ACTIVITIES",
                    message="减少一个可选活动",
                ),
            ),
        ),
    )

    schema = _load_schema("planning-failed-event-v1.schema.json")
    Draft202012Validator(schema).validate(event.model_dump(mode="json", by_alias=True))
