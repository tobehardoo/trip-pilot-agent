"""B10 — structured logging: correlation fields land on records and no
secret/bulk payload ever leaks into a log field or message."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from plan_evaluation_support import make_command, make_result

from trip_agent.worker.processor import process_planning_create
from trip_agent.worker.structured_logging import planning_logger


def test_planning_logger_binds_correlation_fields_to_records(caplog) -> None:
    log = planning_logger(
        "trip_agent.worker.test",
        trace_id="trace-1",
        task_id="task-1",
        trip_id="trip-1",
    )
    with caplog.at_level(logging.INFO):
        log.info("command received: %s", "PLANNING_CREATE")

    record = caplog.records[0]
    assert record.trace_id == "trace-1"
    assert record.task_id == "task-1"
    assert record.trip_id == "trip-1"
    assert record.getMessage() == "command received: PLANNING_CREATE"


def test_planning_logger_null_fields_are_omitted(caplog) -> None:
    log = planning_logger("trip_agent.worker.test", trace_id="trace-1", provider=None)
    with caplog.at_level(logging.INFO):
        log.info("provider started")

    record = caplog.records[0]
    assert record.trace_id == "trace-1"
    assert not hasattr(record, "provider") or record.provider is None


def test_planning_logger_per_call_extra_overrides_base(caplog) -> None:
    log = planning_logger("trip_agent.worker.test", outcome_status="pending")
    with caplog.at_level(logging.INFO):
        log.info("validation result", extra={"outcome_status": "VERIFIED"})

    record = caplog.records[0]
    assert record.outcome_status == "VERIFIED"


class _VerifiedProvider:
    """Controllable planning provider returning a validated VERIFIED result."""

    def __init__(self, result) -> None:
        self._result = result

    async def plan(self, command):
        return self._result

    async def replan(self, command):
        return self._result

    async def repair(self, request):
        return self._result


def test_process_planning_create_emits_structured_boundary_logs(caplog) -> None:
    command = make_command()
    result = make_result()
    provider = _VerifiedProvider(result)

    with caplog.at_level(logging.INFO, logger="trip_agent.worker.processor"):
        outcome = asyncio.run(
            process_planning_create(
                command,
                provider,
                occurred_at=datetime(2026, 8, 10, 12, 0, tzinfo=UTC),
            )
        )

    # B16: unverified-but-savable report -> v10 completed boundary log.
    assert outcome.event_type == "PLANNING_COMPLETED"
    assert outcome.payload.has_blocker is False
    messages = [r.getMessage() for r in caplog.records]
    assert any(m.startswith("command received:") for m in messages)
    assert any(m.startswith("provider started") for m in messages)
    assert any(m.startswith("provider completed") for m in messages)
    assert any(m.startswith("validation result:") for m in messages)
    # Every record carries the command correlation fields.
    for record in caplog.records:
        assert record.trace_id == str(command.trace_id)
        assert record.task_id == str(command.task_id)
        assert record.trip_id == str(command.trip_id)


def test_log_messages_do_not_contain_secret_material(caplog) -> None:
    command = make_command()
    result = make_result()
    provider = _VerifiedProvider(result)

    with caplog.at_level(logging.INFO, logger="trip_agent.worker.processor"):
        asyncio.run(
            process_planning_create(
                command,
                provider,
                occurred_at=datetime(2026, 8, 10, 12, 0, tzinfo=UTC),
            )
        )

    # No full command/event payload, no provider raw response, no secret
    # material may appear anywhere in the emitted log text.
    combined = " | ".join(r.getMessage() for r in caplog.records)
    for forbidden in (
        "constraints",
        "guide_evidence",
        "provider_provenance",
        "accessToken",
        "secret",
        "JWT",
        "Authorization",
    ):
        assert forbidden not in combined
