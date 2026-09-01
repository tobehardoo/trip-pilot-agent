"""Structured logging for the planning worker boundaries.

Field names are the snake_case counterpart of the Java planning pipeline's
MDC keys (camelCase there).  Only correlation/scalar fields are ever placed
on a record; a full Pydantic command/event, a raw provider response and any
secret must never be passed as a field value.

Canonical fields (worker boundary):
    trace_id, event_id, task_id, trip_id, task_type, candidate_type,
    provider, attempt_index, outcome_status, reason_code
"""

from __future__ import annotations

import logging
from typing import Any


class PlanningLogger(logging.LoggerAdapter):
    """LoggerAdapter that merges planning correlation fields into records.

    Every field value becomes a first-class attribute on the emitted
    ``LogRecord``, so tests can assert ``record.trace_id`` etc. via
    ``caplog.records`` without string matching.
    """

    def process(self, msg: Any, kwargs: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
        merged = dict(self.extra)
        merged.update(kwargs.get("extra", {}))
        kwargs["extra"] = merged
        return msg, kwargs


def planning_logger(name: str, **fields: Any) -> PlanningLogger:
    """Return a logger whose records carry the given correlation fields.

    Only non-None scalar values are bound; callers must already have reduced
    any sensitive or bulk data to a safe scalar (id/count/code).
    """
    bound = {key: value for key, value in fields.items() if value is not None}
    return PlanningLogger(logging.getLogger(name), bound)
