"""Production workflow that couples scheduled fetching to durable audit recording."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from trip_agent.acquisition.fetch_models import FetchValidators
from trip_agent.acquisition.models import DiscoveredResource, KnowledgeSource
from trip_agent.acquisition.recording import (
    AcquisitionExecutionRecorder,
    AcquisitionPersisted,
)
from trip_agent.acquisition.scheduling import FetchExecution


class AcquisitionExecutionScheduler(Protocol):
    async def execute(
        self,
        *,
        source: KnowledgeSource,
        resource: DiscoveredResource,
        validators: FetchValidators | None = None,
    ) -> FetchExecution: ...


@dataclass(frozen=True, slots=True)
class AcquisitionWorkflowResult:
    execution: FetchExecution
    persisted: AcquisitionPersisted


class AcquisitionWorkflow:
    """Execute one managed fetch and persist its typed result before returning."""

    def __init__(
        self,
        *,
        scheduler: AcquisitionExecutionScheduler,
        recorder: AcquisitionExecutionRecorder,
        parser_version: str,
    ) -> None:
        if not isinstance(parser_version, str) or not parser_version.strip():
            raise ValueError("parser_version cannot be empty")
        self._scheduler = scheduler
        self._recorder = recorder
        self._parser_version = parser_version.strip()

    async def execute(
        self,
        *,
        source: KnowledgeSource,
        resource: DiscoveredResource,
        published_at: datetime | None = None,
    ) -> AcquisitionWorkflowResult:
        conditional_state = await self._recorder.get_conditional_state(
            source=source,
            resource=resource,
        )
        execution = await self._scheduler.execute(
            source=source,
            resource=resource,
            validators=(conditional_state.validators if conditional_state is not None else None),
        )
        persisted = await self._recorder.record(
            source=source,
            resource=resource,
            execution=execution,
            parser_version=self._parser_version,
            published_at=published_at,
            base_content_hash=(
                conditional_state.content_hash if conditional_state is not None else None
            ),
        )
        return AcquisitionWorkflowResult(execution=execution, persisted=persisted)
