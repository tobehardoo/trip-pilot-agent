import json
from datetime import UTC, datetime
from pathlib import Path

from jsonschema import Draft202012Validator
from test_local_replanning import REPLAN_COMMAND
from test_planning_worker import COMMAND

from trip_agent.domain.planning.protocols import PlanningProviderError
from trip_agent.providers.errors import (
    ProviderErrorCategory,
    ProviderFailureDetails,
    ProviderOperation,
)
from trip_agent.worker.contracts import PlanningCreateCommand, PlanningReplanCommand
from trip_agent.worker.processor import planning_failed_event


def test_provider_failure_is_serialized_as_planning_failed_event_v2() -> None:
    command = PlanningCreateCommand.model_validate(COMMAND)
    failure = PlanningProviderError(
        ProviderFailureDetails(
            category=ProviderErrorCategory.AUTHENTICATION_ERROR,
            error_code="PROVIDER_AUTHENTICATION_FAILED",
            provider="AMAP",
            operation=ProviderOperation.POI_SEARCH,
            retryable=False,
            fallback_allowed=False,
            safe_provider_code="10001",
            safe_message="AMap authentication failed",
            retry_count=0,
            cause_type=None,
            retry_exhausted=False,
        )
    )

    event = planning_failed_event(
        command,
        failure,
        occurred_at=datetime(2026, 7, 31, tzinfo=UTC),
    )
    payload = event.model_dump(mode="json", by_alias=True, exclude_none=True)

    assert payload["schemaVersion"] == 2
    assert payload["payload"] == {
        "status": "FAILED",
        "errorCode": "PROVIDER_AUTHENTICATION_FAILED",
        "errorCategory": "AUTHENTICATION_ERROR",
        "provider": "AMAP",
        "operation": "POI_SEARCH",
        "retryable": False,
        "retryCount": 0,
        "fallbackAttempted": False,
        "fallbackSucceeded": False,
        "safeMessage": "AMap authentication failed",
        "safeProviderCode": "10001",
        "conflicts": [],
        "relaxationSuggestions": [],
    }

    repository = Path(__file__).parents[3]
    schema = json.loads(
        (repository / "contracts/messaging/planning-failed-event-v2.schema.json")
        .read_text(encoding="utf-8")
    )
    Draft202012Validator(schema).validate(payload)


def test_shared_java_fixture_is_readable_by_the_python_v2_model() -> None:
    repository = Path(__file__).parents[3]
    fixture = (
        repository
        / "contracts/fixtures/planning-failed-event-v2/provider-authentication-failed.json"
    )

    from trip_agent.worker.contracts import PlanningFailedEvent

    event = PlanningFailedEvent.model_validate_json(fixture.read_text(encoding="utf-8"))

    assert event.schema_version == 2
    assert event.payload.safe_provider_code == "10001"


def test_internal_replan_failure_reports_the_replanning_operation() -> None:
    command = PlanningReplanCommand.model_validate(REPLAN_COMMAND)

    event = planning_failed_event(command, RuntimeError("unsafe detail"))

    assert event.payload.error_category == "INTERNAL_ERROR"
    assert event.payload.operation == "REPLANNING"
    assert event.payload.safe_message == "Planning failed due to an internal error"
