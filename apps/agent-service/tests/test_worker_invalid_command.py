"""B13_FIX R2 — invalid commands must reach a safe terminal FAILED state.

P0-2: a malformed-but-identifiable command was rejected without any failure
event, leaving the task permanently QUEUED.  The worker must publish a safe
PLANNING_FAILED (stable category/code, no raw body) that Java applies
atomically and idempotently.
"""

import asyncio
import json
from copy import deepcopy
from importlib import import_module
from uuid import UUID

from test_amqp_worker import FakeExchange, FakeIncomingMessage
from test_planning_worker import COMMAND


def _invalid_command() -> dict:
    # The exact P0-2 repro: Java accepted mixed legacy/structured
    # constraints (schema 3 with legacy names and no refs) which the Python
    # model rejects — with a fully valid envelope so the task is known.
    payload = deepcopy(COMMAND)
    payload["schemaVersion"] = 4
    trip = payload["payload"]["trip"]
    trip["arrivalAt"] = "2026-08-01T11:00:00+08:00"
    trip["departureAt"] = "2026-08-02T17:00:00+08:00"
    constraints = trip["constraints"]
    constraints["schemaVersion"] = 3
    constraints["mustVisitPlaces"] = ["陈家祠"]
    constraints.pop("mustVisitPlaceRefs", None)
    constraints.pop("avoidPlaceRefs", None)
    constraints["avoidPlaces"] = []
    return payload


def _published_failed(exchange: FakeExchange) -> dict:
    failed = [item for item in exchange.published if item[1] == "planning.failed"]
    assert failed, "expected a PLANNING_FAILED event on planning.failed"
    return json.loads(failed[-1][0].body)


def test_invalid_command_publishes_safe_terminal_failure_and_acks() -> None:
    amqp = import_module("trip_agent.worker.amqp")
    message = FakeIncomingMessage(json.dumps(_invalid_command()).encode())
    exchange = FakeExchange()

    asyncio.run(amqp.handle_delivery(message, exchange))

    assert message.acked is True
    assert message.rejected_with is None
    body = _published_failed(exchange)
    assert body["eventType"] == "PLANNING_FAILED"
    assert body["schemaVersion"] == 2
    assert body["taskId"] == COMMAND["taskId"]
    assert body["tripId"] == COMMAND["tripId"]
    payload = body["payload"]
    assert payload["status"] == "FAILED"
    assert payload["errorCode"] == "COMMAND_VALIDATION_FAILED"
    assert payload["errorCategory"] == "INVALID_REQUEST"
    assert payload["provider"] == "PLANNER"
    assert payload["retryable"] is False
    assert payload["fallbackAttempted"] is False
    assert payload["fallbackSucceeded"] is False
    # The raw body must never leak into the failure event.
    assert "陈家祠" not in json.dumps(body)
    assert "mustVisitPlaces" not in json.dumps(body)


def test_invalid_command_never_calls_the_provider() -> None:
    amqp = import_module("trip_agent.worker.amqp")

    class _ExplodingProvider:
        async def plan(self, *args, **kwargs):  # pragma: no cover
            raise AssertionError("provider must not be called for invalid commands")

    message = FakeIncomingMessage(json.dumps(_invalid_command()).encode())
    exchange = FakeExchange()
    asyncio.run(amqp.handle_delivery(message, exchange, provider=_ExplodingProvider()))
    assert message.acked is True


def test_failure_event_id_is_deterministic_across_duplicate_deliveries() -> None:
    amqp = import_module("trip_agent.worker.amqp")
    raw = json.dumps(_invalid_command()).encode()

    ids = []
    for _ in range(2):
        exchange = FakeExchange()
        asyncio.run(amqp.handle_delivery(FakeIncomingMessage(raw), exchange))
        ids.append(_published_failed(exchange)["eventId"])
    assert ids[0] == ids[1]
    UUID(ids[0])


def test_unidentifiable_command_is_dead_lettered_without_failure_event() -> None:
    amqp = import_module("trip_agent.worker.amqp")
    broken = {"eventType": "PLANNING_CREATE_REQUESTED", "schemaVersion": 4, "payload": {}}
    message = FakeIncomingMessage(json.dumps(broken).encode())
    exchange = FakeExchange()

    asyncio.run(amqp.handle_delivery(message, exchange))

    assert message.rejected_with is False
    assert exchange.published == []
