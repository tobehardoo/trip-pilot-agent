"""P1.8: AGENT_ASK_USER / AGENT_RESUME cross-language contracts (v1).

The JSON Schemas under ``contracts/messaging/`` are the shared source of
truth; ``contracts/fixtures/agent-*-v1/valid.json`` are read by both the
Python and the Java test suites, so the two parsers are bound to the same
wire shapes.
"""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from trip_agent.worker.contracts import (
    AgentAskUserEvent,
    AgentCompletedEvent,
    AgentResumeCommand,
    AgentRunFinishedEvent,
    AgentStepEvent,
)

CONTRACT_DIRECTORY = Path(__file__).parents[3] / "contracts" / "messaging"
FIXTURE_DIRECTORY = Path(__file__).resolve().parents[3] / "contracts" / "fixtures"
ASK_USER_FIXTURE = FIXTURE_DIRECTORY / "agent-ask-user-event-v1" / "valid.json"
RESUME_FIXTURE = FIXTURE_DIRECTORY / "agent-resume-command-v1" / "valid.json"
STEP_FIXTURE = FIXTURE_DIRECTORY / "agent-step-event-v1" / "valid.json"
COMPLETED_FIXTURE = FIXTURE_DIRECTORY / "agent-completed-event-v1" / "valid.json"
RUN_FINISHED_FIXTURE = FIXTURE_DIRECTORY / "agent-run-finished-event-v1" / "valid.json"


def _load_schema(name: str) -> dict:
    return json.loads((CONTRACT_DIRECTORY / name).read_text(encoding="utf-8"))


def _load_fixture(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _ask_user_wire() -> dict:
    return deepcopy(_load_fixture(ASK_USER_FIXTURE))


def _resume_wire() -> dict:
    return deepcopy(_load_fixture(RESUME_FIXTURE))


# ── AGENT_ASK_USER ──────────────────────────────────────────────────


def test_ask_user_fixture_validates_against_the_schema() -> None:
    Draft202012Validator(_load_schema("agent-ask-user-event-v1.schema.json")).validate(
        _ask_user_wire()
    )


def test_ask_user_model_round_trips_to_the_wire() -> None:
    event = AgentAskUserEvent.model_validate(_ask_user_wire())
    assert event.event_type == "AGENT_ASK_USER"
    assert event.payload.question == "行程从哪天开始？"
    assert event.payload.options == ("2026-10-01", "2026-10-02")
    assert event.payload.expected_type == "DATE"

    schema = _load_schema("agent-ask-user-event-v1.schema.json")
    Draft202012Validator(schema).validate(
        event.model_dump(mode="json", by_alias=True, exclude_none=True)
    )


def test_ask_user_round_trip_without_optional_fields() -> None:
    wire = _ask_user_wire()
    del wire["payload"]["options"]
    del wire["payload"]["expectedType"]
    event = AgentAskUserEvent.model_validate(wire)
    assert event.payload.options is None
    assert event.payload.expected_type is None


def test_ask_user_rejects_more_than_ten_options() -> None:
    wire = _ask_user_wire()
    wire["payload"]["options"] = [f"选项 {index}" for index in range(11)]
    with pytest.raises(ValidationError):
        AgentAskUserEvent.model_validate(wire)


def test_ask_user_rejects_an_unknown_expected_type() -> None:
    wire = _ask_user_wire()
    wire["payload"]["expectedType"] = "EMOJI"
    with pytest.raises(ValidationError):
        AgentAskUserEvent.model_validate(wire)


def test_ask_user_rejects_a_blank_question() -> None:
    wire = _ask_user_wire()
    wire["payload"]["question"] = "  "
    with pytest.raises(ValidationError):
        AgentAskUserEvent.model_validate(wire)


def test_ask_user_rejects_unknown_envelope_fields() -> None:
    wire = _ask_user_wire()
    wire["taskId"] = "5a1b2c3d-4e5f-4a6b-8c9d-0e1f2a3b4c5d"
    with pytest.raises(ValidationError):
        AgentAskUserEvent.model_validate(wire)


# ── AGENT_RESUME ────────────────────────────────────────────────────


def test_resume_fixture_validates_against_the_schema() -> None:
    Draft202012Validator(_load_schema("agent-resume-command-v1.schema.json")).validate(
        _resume_wire()
    )


def test_resume_model_round_trips_to_the_wire() -> None:
    command = AgentResumeCommand.model_validate(_resume_wire())
    assert command.event_type == "AGENT_RESUME"
    assert command.run_id is not None
    assert command.payload.answer == "10月1日出发"

    schema = _load_schema("agent-resume-command-v1.schema.json")
    Draft202012Validator(schema).validate(
        command.model_dump(mode="json", by_alias=True, exclude_none=True)
    )


def test_resume_rejects_an_empty_answer() -> None:
    wire = _resume_wire()
    wire["payload"]["answer"] = ""
    with pytest.raises(ValidationError):
        AgentResumeCommand.model_validate(wire)


def test_resume_rejects_an_answer_beyond_the_bound() -> None:
    wire = _resume_wire()
    wire["payload"]["answer"] = "长" * 2001
    with pytest.raises(ValidationError):
        AgentResumeCommand.model_validate(wire)


def test_resume_requires_a_timezone_in_occurred_at() -> None:
    wire = _resume_wire()
    wire["occurredAt"] = "2026-08-29T09:00:00"
    with pytest.raises(ValidationError, match="timezone"):
        AgentResumeCommand.model_validate(wire)


# ── AGENT_STEP ──────────────────────────────────────────────────────


def test_step_fixture_validates_against_the_schema() -> None:
    Draft202012Validator(_load_schema("agent-step-event-v1.schema.json")).validate(
        _load_fixture(STEP_FIXTURE)
    )


def test_step_model_round_trips_to_the_wire() -> None:
    event = AgentStepEvent.model_validate(_load_fixture(STEP_FIXTURE))
    assert event.payload.seq == 0
    assert event.payload.tool == "ask_user"
    assert event.payload.ok is True
    assert event.payload.error_code is None

    schema = _load_schema("agent-step-event-v1.schema.json")
    Draft202012Validator(schema).validate(
        event.model_dump(mode="json", by_alias=True, exclude_none=True)
    )


def test_step_records_an_error_code_when_the_tool_fails() -> None:
    wire = _load_fixture(STEP_FIXTURE)
    wire["payload"].update({"ok": False, "errorCode": "CAPABILITY_MISSING"})
    event = AgentStepEvent.model_validate(wire)
    assert event.payload.ok is False
    assert event.payload.error_code == "CAPABILITY_MISSING"


# ── AGENT_COMPLETED ─────────────────────────────────────────────────


def test_completed_fixture_validates_against_the_schema() -> None:
    Draft202012Validator(_load_schema("agent-completed-event-v1.schema.json")).validate(
        _load_fixture(COMPLETED_FIXTURE)
    )


def test_completed_model_round_trips_to_the_wire() -> None:
    event = AgentCompletedEvent.model_validate(_load_fixture(COMPLETED_FIXTURE))
    assert event.payload.summary == "行程已生成：测试行程"
    assert event.payload.slots["destination"].value == "成都"
    assert event.payload.slots["destination"].state == "CONFIRMED"

    # AUDIT-01（归边 A）防回归：序列化后的 wire 载荷绝不能携带 itinerary。
    serialized = event.model_dump(mode="json", by_alias=True, exclude_none=True)
    assert "itinerary" not in serialized["payload"]

    schema = _load_schema("agent-completed-event-v1.schema.json")
    Draft202012Validator(schema).validate(serialized)


def test_completed_rejects_a_payload_carrying_an_itinerary() -> None:
    # AUDIT-01（归边 A）：Agent 对话框链不得携带完整 itinerary ——
    # 一旦 serializer 或 handler 重新把 itinerary 塞回 payload，schema
    # （additionalProperties:false）与模型都必须拒绝。
    wire = _load_fixture(COMPLETED_FIXTURE)
    wire["payload"]["itinerary"] = {"title": "测试行程", "days": []}
    with pytest.raises(ValidationError):
        AgentCompletedEvent.model_validate(wire)
    with pytest.raises(Exception):
        Draft202012Validator(_load_schema("agent-completed-event-v1.schema.json")).validate(wire)


# ── AGENT_RUN_FINISHED ──────────────────────────────────────────────


def test_run_finished_fixture_validates_against_the_schema() -> None:
    Draft202012Validator(
        _load_schema("agent-run-finished-event-v1.schema.json")
    ).validate(_load_fixture(RUN_FINISHED_FIXTURE))


def test_run_finished_model_round_trips_to_the_wire() -> None:
    event = AgentRunFinishedEvent.model_validate(_load_fixture(RUN_FINISHED_FIXTURE))
    assert event.payload.status == "STOPPED"
    assert event.payload.reason_code == "CEILING_REACHED"
    assert "步骤上限" in event.payload.message

    schema = _load_schema("agent-run-finished-event-v1.schema.json")
    Draft202012Validator(schema).validate(
        event.model_dump(mode="json", by_alias=True, exclude_none=True)
    )


def test_run_finished_rejects_an_unknown_status() -> None:
    wire = _load_fixture(RUN_FINISHED_FIXTURE)
    wire["payload"]["status"] = "PAUSED"
    with pytest.raises(ValidationError):
        AgentRunFinishedEvent.model_validate(wire)


def test_run_finished_rejects_a_blank_message() -> None:
    wire = _load_fixture(RUN_FINISHED_FIXTURE)
    wire["payload"]["message"] = "   "
    with pytest.raises(ValidationError):
        AgentRunFinishedEvent.model_validate(wire)


def test_run_finished_rejects_unknown_envelope_fields() -> None:
    wire = _load_fixture(RUN_FINISHED_FIXTURE)
    wire["taskId"] = "unexpected"
    with pytest.raises(ValidationError):
        AgentRunFinishedEvent.model_validate(wire)
