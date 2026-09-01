"""Context-bound progress reporting for a single planning delivery."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from contextvars import ContextVar

from trip_agent.worker.contracts import PlanningProgressStage

type ProgressReporter = Callable[
    [PlanningProgressStage, str, Mapping[str, int] | None],
    Awaitable[None],
]

_current_reporter: ContextVar[ProgressReporter | None] = ContextVar(
    "planning_progress_reporter",
    default=None,
)


@asynccontextmanager
async def planning_progress_reporting(reporter: ProgressReporter) -> AsyncIterator[None]:
    token = _current_reporter.set(reporter)
    try:
        yield
    finally:
        _current_reporter.reset(token)


async def report_planning_progress(
    stage: PlanningProgressStage,
    message: str,
    statistics: Mapping[str, int] | None = None,
) -> None:
    reporter = _current_reporter.get()
    if reporter is not None:
        await reporter(stage, message, statistics)
