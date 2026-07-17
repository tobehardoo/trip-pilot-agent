import asyncio
import json
from copy import deepcopy
from importlib import import_module
from typing import Any

import httpx
import pytest
from pydantic import ValidationError
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


class NoopJsonCache:
    async def get(self, key: str) -> str | None:
        del key
        return None

    async def set(self, key: str, value: str, *, ttl_seconds: int) -> None:
        del key, value, ttl_seconds


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
    assert body["schemaVersion"] == 2
    assert body["taskId"] == COMMAND["taskId"]
    assert body["payload"]["itinerary"]["estimatedTotalCost"] == 0
    assert isinstance(body["payload"]["itinerary"]["estimatedTotalCost"], int | float)
    activity = body["payload"]["itinerary"]["days"][0]["activities"][0]
    assert "providerPoiId" not in activity
    assert "coordinates" not in activity
    assert "address" not in activity


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


def test_real_worker_settings_require_a_secret_amap_key_at_startup() -> None:
    amqp = import_module("trip_agent.worker.amqp")

    with pytest.raises(ValidationError):
        amqp.WorkerSettings(_env_file=None, demo_mode=False)

    settings = amqp.WorkerSettings(
        _env_file=None,
        demo_mode=False,
        amap_web_service_key="worker-local-secret",
    )

    assert settings.amap_web_service_key.get_secret_value() == "worker-local-secret"
    assert "worker-local-secret" not in repr(settings)


def test_real_worker_provider_factory_builds_amap_v2_with_demo_fallback() -> None:
    amqp = import_module("trip_agent.worker.amqp")
    contracts = import_module("trip_agent.worker.contracts")
    processor = import_module("trip_agent.worker.processor")
    settings = amqp.WorkerSettings(
        _env_file=None,
        demo_mode=False,
        amap_web_service_key="factory-test-key",
    )

    def handle(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "1",
                "info": "OK",
                "infocode": "10000",
                "pois": [
                    {
                        "id": f"poi-{index}",
                        "name": f"真实地点 {index}",
                        "location": f"113.3{index},23.1{index}",
                        "type": "风景名胜",
                        "typecode": "110000",
                        "pname": "广东省",
                        "cityname": "广州市",
                        "adname": "天河区",
                        "address": f"广州地址 {index}",
                    }
                    for index in range(1, 5)
                ],
            },
        )

    async def run_scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            provider = amqp.build_planning_provider(
                settings,
                http_client=client,
                cache=NoopJsonCache(),
            )
            command = contracts.PlanningCreateCommand.model_validate(COMMAND)
            return await processor.process_planning_create(command, provider)

    completed = asyncio.run(run_scenario())

    assert completed.schema_version == 2
    assert completed.payload.provider == "AMAP"
    assert completed.payload.itinerary.days[0].activities[0].provider_poi_id == "poi-1"


def test_real_worker_runtime_owns_lazy_http_and_redis_resources() -> None:
    amqp = import_module("trip_agent.worker.amqp")
    processor = import_module("trip_agent.worker.processor")
    settings = amqp.WorkerSettings(
        _env_file=None,
        demo_mode=False,
        amap_web_service_key="runtime-test-key",
        redis_password="p@ss word",
    )

    async def run_scenario() -> None:
        async with amqp.planning_provider_runtime(settings) as provider:
            assert isinstance(provider, processor.FallbackPlanningProvider)
            assert "p%40ss%20word" in settings.redis_connection_url()

    asyncio.run(run_scenario())
