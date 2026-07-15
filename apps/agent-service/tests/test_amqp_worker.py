import asyncio
import json
from copy import deepcopy
from importlib import import_module
from typing import Any

from test_planning_worker import COMMAND


class FakeIncomingMessage:
    def __init__(self, body: bytes) -> None:
        self.body = body
        self.acked = False
        self.rejected_with: bool | None = None
        self.nacked_with: bool | None = None

    async def ack(self) -> None:
        self.acked = True

    async def reject(self, *, requeue: bool) -> None:
        self.rejected_with = requeue

    async def nack(self, *, requeue: bool) -> None:
        self.nacked_with = requeue


class FakeExchange:
    def __init__(self, failure: Exception | None = None) -> None:
        self.failure = failure
        self.published: list[tuple[Any, str, bool]] = []

    async def publish(self, message: Any, *, routing_key: str, mandatory: bool) -> None:
        if self.failure is not None:
            raise self.failure
        self.published.append((message, routing_key, mandatory))


def test_valid_command_is_acked_only_after_completed_event_is_published() -> None:
    amqp = import_module("trip_agent.worker.amqp")
    handle = getattr(amqp, "handle_delivery", None)
    assert handle is not None
    message = FakeIncomingMessage(json.dumps(COMMAND).encode())
    exchange = FakeExchange()

    asyncio.run(handle(message, exchange))

    assert message.acked is True
    assert message.rejected_with is None
    assert message.nacked_with is None
    assert len(exchange.published) == 1
    published, routing_key, mandatory = exchange.published[0]
    assert routing_key == "planning.completed"
    assert mandatory is True
    assert published.content_type == "application/json"
    assert published.delivery_mode.name == "PERSISTENT"
    assert published.message_id is not None
    body = json.loads(published.body)
    assert body["eventType"] == "PLANNING_COMPLETED"
    assert body["taskId"] == COMMAND["taskId"]
    assert body["payload"]["itinerary"]["estimatedTotalCost"] == 0
    assert isinstance(body["payload"]["itinerary"]["estimatedTotalCost"], int | float)


def test_invalid_command_is_rejected_without_requeue() -> None:
    amqp = import_module("trip_agent.worker.amqp")
    handle = getattr(amqp, "handle_delivery", None)
    assert handle is not None
    message = FakeIncomingMessage(b'{"eventType":"UNKNOWN"}')
    exchange = FakeExchange()

    asyncio.run(handle(message, exchange))

    assert message.acked is False
    assert message.rejected_with is False
    assert message.nacked_with is None
    assert exchange.published == []


def test_mixed_timezone_schedule_is_rejected_without_stalling_delivery() -> None:
    amqp = import_module("trip_agent.worker.amqp")
    handle = getattr(amqp, "handle_delivery", None)
    assert handle is not None
    invalid = deepcopy(COMMAND)
    invalid["payload"]["trip"]["constraints"]["fixedSchedules"] = [
        {
            "placeName": "广州塔",
            "startTime": "2026-08-02T19:00:00",
            "endTime": "2026-08-02T21:00:00+08:00",
        }
    ]
    message = FakeIncomingMessage(json.dumps(invalid).encode())
    exchange = FakeExchange()

    asyncio.run(handle(message, exchange))

    assert message.acked is False
    assert message.rejected_with is False
    assert message.nacked_with is None
    assert exchange.published == []


def test_event_publication_failure_requeues_the_command() -> None:
    amqp = import_module("trip_agent.worker.amqp")
    handle = getattr(amqp, "handle_delivery", None)
    assert handle is not None
    message = FakeIncomingMessage(json.dumps(COMMAND).encode())
    exchange = FakeExchange(RuntimeError("broker channel closed"))

    asyncio.run(handle(message, exchange))

    assert message.acked is False
    assert message.rejected_with is None
    assert message.nacked_with is True
