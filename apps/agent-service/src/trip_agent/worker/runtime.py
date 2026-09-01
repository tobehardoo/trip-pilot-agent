"""Worker runtime composition root.

F-3b: the AMQP transport (``worker.amqp``) owns delivery/consumption only;
every provider decision — settings validation, mode resolution, retry and
fallback policies, resource lifetimes (HTTP, Redis, Postgres) — lives here so
the transport never needs to know which providers are wired.

``WorkerSettings`` deliberately keeps its own ``resolved_provider_mode``
(fails closed to DEMO_ONLY when unset, B12) instead of delegating to
``providers.settings.resolve_provider_mode``: a missing key must never
auto-select a real provider in the worker process.
"""

import logging
from collections.abc import AsyncIterator, Awaitable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, Self
from urllib.parse import quote
from uuid import UUID

import httpx
import psycopg
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from trip_agent.acquisition.registry import SourceCatalog
from trip_agent.domain.planning.protocols import (
    KnowledgeEvidenceProvider,
    PlanningProvider,
)
from trip_agent.infrastructure.amap.planning_provider import AmapPlanningProvider
from trip_agent.infrastructure.demo.knowledge_provider import DemoKnowledgeEvidenceProvider
from trip_agent.infrastructure.demo.planning_provider import DemoPlanningProvider
from trip_agent.providers.errors import (
    ProviderErrorCategory,
    ProviderExecutionMode,
    ProviderFallbackPolicy,
)
from trip_agent.providers.map import AmapMapProvider, JsonCache
from trip_agent.providers.redis_cache import RedisJsonCache
from trip_agent.providers.retry import (
    ProviderRetryPolicy,
    RetryingMapProvider,
    RetryingRouteProvider,
)
from trip_agent.providers.route import (
    AmapRouteProvider,
    AmapTransitProvider,
    DemoRouteProvider,
)
from trip_agent.retrieval.embeddings import (
    DashScopeEmbeddingProvider,
    EmbeddingProvider,
    HashEmbeddingProvider,
)
from trip_agent.retrieval.repository import PsycopgKnowledgeRepository
from trip_agent.worker.knowledge import (
    KnowledgeFreshnessProvider,
    KnowledgeSearchRepository,
    RetrievalKnowledgeEvidenceProvider,
    StaticCatalogKnowledgeFreshnessProvider,
)
from trip_agent.workflow.planner_pipeline import FallbackPlanningProvider

logger = logging.getLogger("trip_agent.worker")


class CancellationOracle(Protocol):
    def is_cancelled(self, task_id: UUID) -> Awaitable[bool]: ...


class PsycopgCancellationOracle:
    """Checks cancellation status via a persistent database connection.

    Uses a single long-lived async connection instead of opening a new
    connection per check, avoiding connection-storm under load.
    """

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url
        self._connection: psycopg.AsyncConnection | None = None

    async def _ensure_connection(self) -> psycopg.AsyncConnection:
        if self._connection is None or self._connection.closed:
            self._connection = await psycopg.AsyncConnection.connect(self._database_url)
        return self._connection

    async def is_cancelled(self, task_id: UUID) -> bool:
        try:
            connection = await self._ensure_connection()
            async with connection.cursor() as cursor:
                await cursor.execute(
                    "SELECT status FROM business.planning_task WHERE id = %s",
                    (task_id,),
                )
                row = await cursor.fetchone()
        except psycopg.Error:
            # Connection may have dropped — reset and let the next call
            # re-establish it.
            self._connection = None
            raise
        return row is not None and row[0] == "CANCELLED"

    async def close(self) -> None:
        if self._connection is not None and not self._connection.closed:
            await self._connection.close()


class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="",
        env_file=(".env", "../../.env"),
        extra="ignore",
        frozen=True,
    )

    rabbitmq_host: str = "localhost"
    rabbitmq_port: int = 5672
    rabbitmq_user: str = "trip_pilot"
    rabbitmq_password: str = "replace-with-local-password"
    provider_mode: ProviderExecutionMode | None = None
    amap_web_service_key: SecretStr | None = None
    amap_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    provider_max_attempts: int = Field(default=3, ge=1, le=5)
    provider_retry_base_delay_seconds: float = Field(default=0.2, ge=0, le=5)
    provider_retry_max_delay_seconds: float = Field(default=2.0, ge=0, le=30)
    provider_retry_max_elapsed_seconds: float = Field(default=5.0, gt=0, le=60)
    provider_retry_jitter_ratio: float = Field(default=0.2, ge=0, le=1)
    provider_fallback_categories: frozenset[ProviderErrorCategory] = frozenset()
    poi_cache_ttl_seconds: int = Field(default=86_400, gt=0)
    route_cache_ttl_seconds: int = Field(default=3_600, gt=0)
    redis_host: str = "localhost"
    redis_port: int = Field(default=6379, ge=1, le=65_535)
    redis_password: SecretStr = SecretStr("replace-with-local-password")
    redis_db: int = Field(default=0, ge=0)
    redis_timeout_seconds: float = Field(default=2.0, gt=0, le=30)
    knowledge_database_url: SecretStr | None = None
    knowledge_embedding_provider: Literal["demo", "dashscope"] = "demo"
    knowledge_embedding_dimensions: int = Field(default=1024, ge=1, le=4096)
    knowledge_embedding_model: str = "text-embedding-v4"
    dashscope_api_key: SecretStr | None = None
    dashscope_embedding_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    dashscope_embedding_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    knowledge_source_directory: Path = Path("../../knowledge/sources")
    postgres_host: str = "localhost"
    postgres_port: int = Field(default=5432, ge=1, le=65_535)
    postgres_db: str = "trip_pilot"
    postgres_user: str = "trip_pilot"
    postgres_password: SecretStr = SecretStr("local-development-only")

    @model_validator(mode="after")
    def require_real_provider_key(self) -> Self:
        ProviderFallbackPolicy(additional_allowed_categories=self.provider_fallback_categories)
        key = self.amap_web_service_key
        if self.resolved_provider_mode != ProviderExecutionMode.DEMO_ONLY and (
            key is None or not key.get_secret_value().strip()
        ):
            raise ValueError("AMAP_WEB_SERVICE_KEY is required in a real provider mode")
        embedding_key = self.dashscope_api_key
        if (
            self.resolved_provider_mode != ProviderExecutionMode.DEMO_ONLY
            and self.knowledge_embedding_provider == "dashscope"
            and (embedding_key is None or not embedding_key.get_secret_value().strip())
        ):
            raise ValueError("DASHSCOPE_API_KEY is required for DashScope embeddings")
        return self

    @property
    def resolved_provider_mode(self) -> ProviderExecutionMode:
        if self.provider_mode is not None:
            return self.provider_mode
        return ProviderExecutionMode.DEMO_ONLY

    def provider_retry_policy(self) -> ProviderRetryPolicy:
        return ProviderRetryPolicy(
            max_attempts=self.provider_max_attempts,
            base_delay_seconds=self.provider_retry_base_delay_seconds,
            max_delay_seconds=self.provider_retry_max_delay_seconds,
            max_elapsed_seconds=self.provider_retry_max_elapsed_seconds,
            jitter_ratio=self.provider_retry_jitter_ratio,
        )

    def provider_fallback_policy(self) -> ProviderFallbackPolicy:
        return ProviderFallbackPolicy(
            additional_allowed_categories=self.provider_fallback_categories
        )

    def redis_connection_url(self) -> str:
        password = quote(self.redis_password.get_secret_value(), safe="")
        return f"redis://:{password}@{self.redis_host}:{self.redis_port}/{self.redis_db}"

    def knowledge_connection_url(self) -> str:
        if self.knowledge_database_url is not None:
            configured = self.knowledge_database_url.get_secret_value().strip()
            if configured:
                return configured
        return self.business_connection_url()

    def business_connection_url(self) -> str:
        password = quote(self.postgres_password.get_secret_value(), safe="")
        return (
            f"postgresql://{quote(self.postgres_user, safe='')}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}/{quote(self.postgres_db, safe='')}"
        )


@dataclass(frozen=True, slots=True)
class WorkerRuntime:
    planning_provider: PlanningProvider
    knowledge_provider: KnowledgeEvidenceProvider
    cancellation_oracle: CancellationOracle


def build_planning_provider(
    settings: WorkerSettings,
    *,
    http_client: httpx.AsyncClient | None = None,
    cache: JsonCache | None = None,
) -> PlanningProvider:
    mode = settings.resolved_provider_mode
    if mode == ProviderExecutionMode.DEMO_ONLY:
        return DemoPlanningProvider()
    if http_client is None:
        raise ValueError("HTTP client is required in real provider mode")
    key = settings.amap_web_service_key
    if key is None:
        raise ValueError("AMap key is required in real provider mode")
    retry_policy = settings.provider_retry_policy()
    amap_map = RetryingMapProvider(
        AmapMapProvider(
            api_key=key.get_secret_value(),
            http_client=http_client,
            cache=cache,
            cache_ttl_seconds=settings.poi_cache_ttl_seconds,
        ),
        retry_policy,
    )
    amap_route = RetryingRouteProvider(
        AmapRouteProvider(
            api_key=key.get_secret_value(),
            http_client=http_client,
            cache=cache,
            cache_ttl_seconds=settings.route_cache_ttl_seconds,
        ),
        retry_policy,
    )
    amap_transit = RetryingRouteProvider(
        AmapTransitProvider(
            api_key=key.get_secret_value(),
            http_client=http_client,
            cache=cache,
            cache_ttl_seconds=settings.route_cache_ttl_seconds,
        ),
        retry_policy,
    )
    policy = settings.provider_fallback_policy()
    primary = AmapPlanningProvider(
        amap_map,
        amap_route,
        transit_route=amap_transit,
        route_fallback=(
            DemoRouteProvider()
            if mode == ProviderExecutionMode.REAL_WITH_EXPLICIT_FALLBACK
            else None
        ),
        provider_mode=mode,
        fallback_policy=policy,
    )
    if mode == ProviderExecutionMode.REAL_ONLY:
        return primary
    return FallbackPlanningProvider(
        primary,
        DemoPlanningProvider(),
        provider_mode=mode,
        fallback_policy=policy,
    )


def build_knowledge_provider(
    settings: WorkerSettings,
    *,
    embedding_provider: EmbeddingProvider | None = None,
    repository: KnowledgeSearchRepository | None = None,
    freshness_provider: KnowledgeFreshnessProvider | None = None,
) -> KnowledgeEvidenceProvider:
    if settings.resolved_provider_mode == ProviderExecutionMode.DEMO_ONLY:
        return DemoKnowledgeEvidenceProvider()
    database_url = settings.knowledge_connection_url()
    selected_embedding = embedding_provider or _configured_embedding_provider(settings)
    selected_repository = repository or PsycopgKnowledgeRepository(database_url)
    if freshness_provider is None:
        freshness_provider = StaticCatalogKnowledgeFreshnessProvider(
            catalog=SourceCatalog.load_directory(settings.knowledge_source_directory),
        )
    return RetrievalKnowledgeEvidenceProvider(
        embedding_provider=selected_embedding,
        repository=selected_repository,
        freshness_provider=freshness_provider,
    )


def _configured_embedding_provider(settings: WorkerSettings) -> EmbeddingProvider:
    if settings.knowledge_embedding_provider == "demo":
        return HashEmbeddingProvider(dimensions=settings.knowledge_embedding_dimensions)
    key = settings.dashscope_api_key
    if key is None:
        raise ValueError("DASHSCOPE_API_KEY is required for DashScope embeddings")
    return DashScopeEmbeddingProvider(
        api_key=key.get_secret_value(),
        base_url=settings.dashscope_embedding_base_url,
        model_name=settings.knowledge_embedding_model,
        dimensions=settings.knowledge_embedding_dimensions,
        timeout_seconds=settings.dashscope_embedding_timeout_seconds,
    )


@asynccontextmanager
async def planning_provider_runtime(
    settings: WorkerSettings,
) -> AsyncIterator[PlanningProvider]:
    logger.info("provider_mode=%s", settings.resolved_provider_mode.value)
    if settings.resolved_provider_mode == ProviderExecutionMode.DEMO_ONLY:
        yield DemoPlanningProvider()
        return
    async with httpx.AsyncClient(timeout=settings.amap_timeout_seconds) as http_client:
        cache = RedisJsonCache.from_url(
            settings.redis_connection_url(),
            socket_connect_timeout=settings.redis_timeout_seconds,
            socket_timeout=settings.redis_timeout_seconds,
        )
        try:
            yield build_planning_provider(
                settings,
                http_client=http_client,
                cache=cache,
            )
        finally:
            await cache.aclose()


@asynccontextmanager
async def worker_runtime(settings: WorkerSettings) -> AsyncIterator[WorkerRuntime]:
    async with planning_provider_runtime(settings) as planning_provider:
        yield WorkerRuntime(
            planning_provider=planning_provider,
            knowledge_provider=build_knowledge_provider(settings),
            cancellation_oracle=PsycopgCancellationOracle(settings.business_connection_url()),
        )
