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
    def __init__(self) -> None:
        self.ttl_seconds: list[int] = []

    async def get(self, key: str) -> str | None:
        del key
        return None

    async def set(self, key: str, value: str, *, ttl_seconds: int) -> None:
        del key, value
        self.ttl_seconds.append(ttl_seconds)


def _cancel_command() -> dict[str, object]:
    return {
        "eventType": "PLANNING_CANCEL_REQUESTED",
        "schemaVersion": 1,
        "eventId": "5e658e0e-9302-4ac8-8457-e0e39869906c",
        "traceId": COMMAND["traceId"],
        "taskId": COMMAND["taskId"],
        "tripId": COMMAND["tripId"],
        "occurredAt": "2026-07-23T04:00:00Z",
    }


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
    assert body["schemaVersion"] == 4
    assert body["taskId"] == COMMAND["taskId"]
    assert body["payload"]["itinerary"]["estimatedTotalCost"] == 0
    assert isinstance(body["payload"]["itinerary"]["estimatedTotalCost"], int | float)
    activity = body["payload"]["itinerary"]["days"][0]["activities"][0]
    assert "providerPoiId" not in activity
    assert "coordinates" not in activity
    assert "address" not in activity
    assert body["payload"]["itinerary"]["days"][0]["transitLegs"] == []
    assert body["payload"]["knowledge"] == {
        "status": "DEMO",
        "query": "广州 美食 历史 FRIENDS",
        "citations": [],
        "freshness": {"status": "UNAVAILABLE"},
        "message": "演示模式未使用生产知识检索",
    }


def test_cancel_command_suppresses_a_queued_planning_delivery() -> None:
    amqp = import_module("trip_agent.worker.amqp")
    registry = amqp.CancellationRegistry()
    cancel = FakeIncomingMessage(json.dumps(_cancel_command()).encode())
    create = FakeIncomingMessage(json.dumps(COMMAND).encode())
    exchange = FakeExchange()

    async def scenario() -> None:
        await amqp.handle_cancel_delivery(cancel, registry)
        await amqp.handle_delivery(create, exchange, cancellation_registry=registry)

    asyncio.run(scenario())

    assert cancel.acked is True
    assert create.acked is True
    assert exchange.published == []


def test_cancel_command_interrupts_an_in_flight_provider_without_publishing() -> None:
    amqp = import_module("trip_agent.worker.amqp")
    registry = amqp.CancellationRegistry()
    create = FakeIncomingMessage(json.dumps(COMMAND).encode())
    cancel = FakeIncomingMessage(json.dumps(_cancel_command()).encode())
    exchange = FakeExchange()
    started = asyncio.Event()
    stopped = asyncio.Event()

    class BlockingProvider:
        async def plan(self, command: object):
            del command
            started.set()
            try:
                await asyncio.Future()
            finally:
                stopped.set()

    async def scenario() -> None:
        delivery = asyncio.create_task(
            amqp.handle_delivery(
                create,
                exchange,
                provider=BlockingProvider(),
                cancellation_registry=registry,
            )
        )
        await asyncio.wait_for(started.wait(), timeout=1)
        await amqp.handle_cancel_delivery(cancel, registry)
        await asyncio.wait_for(delivery, timeout=1)

    asyncio.run(scenario())

    assert stopped.is_set()
    assert cancel.acked is True
    assert create.acked is True
    assert create.nacked_with is None
    assert exchange.published == []


def test_authoritative_cancelled_status_suppresses_a_late_completion() -> None:
    amqp = import_module("trip_agent.worker.amqp")
    create = FakeIncomingMessage(json.dumps(COMMAND).encode())
    exchange = FakeExchange()

    class CancelledStatus:
        async def is_cancelled(self, task_id: object) -> bool:
            assert str(task_id) == COMMAND["taskId"]
            return True

    asyncio.run(
        amqp.handle_delivery(
            create,
            exchange,
            cancellation_oracle=CancelledStatus(),
        )
    )

    assert create.acked is True
    assert create.nacked_with is None
    assert exchange.published == []


def test_maximum_valid_preferences_publish_a_bounded_knowledge_query() -> None:
    amqp = import_module("trip_agent.worker.amqp")
    command = deepcopy(COMMAND)
    command["payload"]["trip"]["destination"] = "广" * 120
    command["payload"]["trip"]["constraints"]["preferences"] = [
        f"偏好{index:02d}" + "长" * 54 for index in range(30)
    ]
    message = FakeIncomingMessage(json.dumps(command).encode())
    exchange = FakeExchange()

    asyncio.run(amqp.handle_delivery(message, exchange))

    assert message.acked is True
    assert message.nacked_with is None
    body = json.loads(exchange.published[0][0].body)
    query = body["payload"]["knowledge"]["query"]
    assert 1 <= len(query) <= 200
    assert query.startswith("广" * 120)


def test_delivery_uses_the_configured_knowledge_evidence_provider() -> None:
    amqp = import_module("trip_agent.worker.amqp")
    contracts = import_module("trip_agent.worker.contracts")
    message = FakeIncomingMessage(json.dumps(COMMAND).encode())
    exchange = FakeExchange()

    class KnowledgeProvider:
        async def get_evidence(self, command: object):
            del command
            return contracts.KnowledgeEvidence(
                status="REAL",
                query="广州 历史",
                citations=(
                    contracts.KnowledgeCitationSnapshot(
                        document_id="doc-1",
                        document_version=1,
                        chunk_id="doc-1-v1-c0",
                        chunk_index=0,
                        title="广州资料",
                        source_url="https://www.gz.gov.cn/doc-1",
                        source_name="广州市人民政府",
                        collected_at="2026-07-22T02:00:00Z",
                        reliability_level="official",
                        similarity=0.9,
                    ),
                ),
                freshness=contracts.KnowledgeFreshness(
                    status="FRESH",
                    checked_at="2026-07-23T01:00:00Z",
                ),
            )

    asyncio.run(
        amqp.handle_delivery(
            message,
            exchange,
            knowledge_provider=KnowledgeProvider(),
        )
    )

    body = json.loads(exchange.published[0][0].body)
    assert body["payload"]["knowledge"]["status"] == "REAL"
    assert body["payload"]["knowledge"]["citations"][0]["documentId"] == "doc-1"


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


def test_infeasible_plan_publishes_an_actionable_failure_and_acks() -> None:
    amqp = import_module("trip_agent.worker.amqp")
    optimization = import_module("trip_agent.planning.optimization")
    processor = import_module("trip_agent.worker.processor")
    message = FakeIncomingMessage(json.dumps(COMMAND).encode())
    exchange = FakeExchange()

    class InfeasibleProvider:
        async def plan(self, command: object):
            del command
            raise processor.PlanningInfeasibleError(
                (optimization.OptimizationConflict(
                    "INSUFFICIENT_DAY_CAPACITY",
                    "活动、交通与固定安排无法同时放入可用时间",
                    ("不可移动安排",),
                ),),
                (optimization.RelaxationSuggestion(
                    "REDUCE_OPTIONAL_ACTIVITIES",
                    "减少一个可选活动",
                ),),
            )

    asyncio.run(amqp.handle_delivery(message, exchange, provider=InfeasibleProvider()))

    assert message.acked is True
    assert message.nacked_with is None
    published, routing_key, mandatory = exchange.published[0]
    assert routing_key == "planning.failed"
    assert mandatory is True
    body = json.loads(published.body)
    assert body["eventType"] == "PLANNING_FAILED"
    assert body["schemaVersion"] == 1
    assert body["payload"]["errorCode"] == "NO_FEASIBLE_ITINERARY"
    assert body["payload"]["conflicts"][0]["code"] == "INSUFFICIENT_DAY_CAPACITY"
    assert body["payload"]["relaxationSuggestions"][0]["code"] == (
        "REDUCE_OPTIONAL_ACTIVITIES"
    )


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


def test_real_dashscope_worker_settings_require_a_secret_embedding_key() -> None:
    amqp = import_module("trip_agent.worker.amqp")

    with pytest.raises(ValidationError, match="DASHSCOPE_API_KEY"):
        amqp.WorkerSettings(
            _env_file=None,
            demo_mode=False,
            amap_web_service_key="worker-local-secret",
            knowledge_embedding_provider="dashscope",
        )

    settings = amqp.WorkerSettings(
        _env_file=None,
        demo_mode=False,
        amap_web_service_key="worker-local-secret",
        knowledge_embedding_provider="dashscope",
        dashscope_api_key="embedding-local-secret",
    )

    assert settings.dashscope_api_key.get_secret_value() == "embedding-local-secret"
    assert "embedding-local-secret" not in repr(settings)


def test_business_database_url_never_uses_the_optional_knowledge_store_override() -> None:
    amqp = import_module("trip_agent.worker.amqp")
    settings = amqp.WorkerSettings(
        _env_file=None,
        knowledge_database_url="postgresql://knowledge:secret@knowledge-db/rag",
        postgres_host="business-db",
        postgres_port=5433,
        postgres_db="trip_business",
        postgres_user="business_user",
        postgres_password="business-secret",
    )

    assert settings.knowledge_connection_url() == (
        "postgresql://knowledge:secret@knowledge-db/rag"
    )
    assert settings.business_connection_url() == (
        "postgresql://business_user:business-secret@business-db:5433/trip_business"
    )


def test_real_worker_provider_factory_builds_amap_v3_with_routes_and_demo_fallback() -> None:
    amqp = import_module("trip_agent.worker.amqp")
    contracts = import_module("trip_agent.worker.contracts")
    processor = import_module("trip_agent.worker.processor")
    settings = amqp.WorkerSettings(
        _env_file=None,
        demo_mode=False,
        amap_web_service_key="factory-test-key",
    )

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/v5/direction/walking"):
            return httpx.Response(
                200,
                json={
                    "status": "1",
                    "info": "OK",
                    "infocode": "10000",
                    "count": "1",
                    "route": {
                        "origin": "113.31,23.11",
                        "destination": "113.32,23.12",
                        "paths": [
                            {
                                "distance": "1200",
                                "cost": {"duration": "900"},
                                "steps": [
                                    {
                                        "instruction": "Walk to the next activity",
                                        "step_distance": "1200",
                                        "cost": {"duration": "900"},
                                        "polyline": "113.31,23.11;113.32,23.12",
                                    }
                                ],
                            }
                        ],
                    },
                },
            )
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
                    for index in range(1, 9)
                ],
            },
        )

    async def run_scenario():
        cache = NoopJsonCache()
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            provider = amqp.build_planning_provider(
                settings,
                http_client=client,
                cache=cache,
            )
            command = contracts.PlanningCreateCommand.model_validate(COMMAND)
            completed = await processor.process_planning_create(command, provider)
            return completed, cache.ttl_seconds

    completed, cache_ttls = asyncio.run(run_scenario())

    assert completed.schema_version == 4
    assert completed.payload.provider == "AMAP"
    assert completed.payload.itinerary.days[0].activities[0].provider_poi_id == "poi-1"
    assert completed.payload.itinerary.days[0].activities[1].provider_poi_id == "poi-2"
    leg = completed.payload.itinerary.days[0].transit_legs[0]
    assert leg.provider == "AMAP"
    assert leg.distance_meters == 1200
    assert leg.estimated is False
    assert settings.poi_cache_ttl_seconds in cache_ttls
    assert settings.route_cache_ttl_seconds in cache_ttls


def test_demo_worker_factory_and_runtime_do_not_allocate_external_resources() -> None:
    amqp = import_module("trip_agent.worker.amqp")
    processor = import_module("trip_agent.worker.processor")
    settings = amqp.WorkerSettings(_env_file=None, demo_mode=True)

    assert isinstance(amqp.build_planning_provider(settings), processor.DemoPlanningProvider)

    async def run_scenario() -> None:
        async with amqp.planning_provider_runtime(settings) as provider:
            assert isinstance(provider, processor.DemoPlanningProvider)

    asyncio.run(run_scenario())


def test_worker_runtime_composes_demo_planning_and_knowledge_ports() -> None:
    amqp = import_module("trip_agent.worker.amqp")
    processor = import_module("trip_agent.worker.processor")
    settings = amqp.WorkerSettings(_env_file=None, demo_mode=True)

    async def run_scenario() -> None:
        async with amqp.worker_runtime(settings) as runtime:
            assert isinstance(runtime.planning_provider, processor.DemoPlanningProvider)
            assert isinstance(
                runtime.knowledge_provider,
                processor.DemoKnowledgeEvidenceProvider,
            )

    asyncio.run(run_scenario())


def test_real_worker_knowledge_factory_uses_the_retrieval_port() -> None:
    amqp = import_module("trip_agent.worker.amqp")
    embeddings = import_module("trip_agent.retrieval.embeddings")
    knowledge = import_module("trip_agent.worker.knowledge")
    settings = amqp.WorkerSettings(
        _env_file=None,
        demo_mode=False,
        amap_web_service_key="runtime-test-key",
    )

    class Repository:
        async def search(self, request: object):
            del request
            return ()

    class FreshnessProvider:
        async def assess(self, city: str, citations: tuple[object, ...]):
            del city, citations
            raise AssertionError("factory construction must not perform I/O")

    provider = amqp.build_knowledge_provider(
        settings,
        embedding_provider=embeddings.HashEmbeddingProvider(dimensions=8),
        repository=Repository(),
        freshness_provider=FreshnessProvider(),
    )

    assert isinstance(provider, knowledge.RetrievalKnowledgeEvidenceProvider)


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
