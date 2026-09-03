"""PostgreSQL persistence for agent runs: trajectory, idempotency, checkpoints.

P1.6 / P1.7.  The schema is Python-side only (the existing ``agent`` schema);
the Java business schema is never touched.  Migrations follow the acquisition
pattern: checksummed ``V*__*.sql`` files applied under an advisory lock and
tracked in ``agent.agent_schema_migration``.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from trip_agent.agent.graph import AgentRunResult
from trip_agent.agent.state import AgentState, agent_state_from_dict, agent_state_to_dict

logger = logging.getLogger(__name__)

RunStatus = Literal[
    "RUNNING", "WAITING_USER", "COMPLETED", "SUPERSEDED", "EXPIRED", "STOPPED", "FAILED"
]

_STATUS_FOR_STOP_REASON: dict[str, str] = {
    "WAITING_USER": "WAITING_USER",
    "EMITTED": "COMPLETED",
    "ANSWERED": "COMPLETED",
    "CEILING_REACHED": "STOPPED",
    "LLM_BUDGET_EXHAUSTED": "STOPPED",
}


def status_for_stop_reason(stop_reason: str | None) -> str:
    """Map a loop stop reason onto a persisted run status."""
    if stop_reason is None:
        return "STOPPED"
    return _STATUS_FOR_STOP_REASON.get(stop_reason, "STOPPED")


@dataclass(frozen=True, slots=True)
class AgentRunStarted:
    """Outcome of starting (or de-duplicating) one agent run."""

    run_id: str
    created: bool


@dataclass(frozen=True, slots=True)
class AgentRunRecord:
    """A persisted run's identity and outcome."""

    run_id: str
    command_event_id: str | None
    trip_id: str | None
    status: str
    stop_reason: str | None
    answer: str | None
    pending_question: str | None
    updated_at: datetime | None = None


class PsycopgAgentRunRepository:
    """Persist agent runs, steps and checkpoints."""

    _migration_directory = Path(__file__).with_name("migrations")

    def __init__(self, database_url: str) -> None:
        if not database_url.strip():
            raise ValueError("agent database URL cannot be empty")
        self._database_url = database_url.strip()

    async def migrate(self) -> None:
        await asyncio.to_thread(self._migrate_sync)

    async def start_run(
        self,
        *,
        run_id: str,
        command_event_id: str | None,
        trip_id: str | None,
    ) -> AgentRunStarted:
        return await asyncio.to_thread(
            self._start_run_sync, run_id, command_event_id, trip_id
        )

    async def ensure_run(self, *, run_id: str, status: str = "RUNNING") -> None:
        """Idempotently create a run row so a checkpoint can reference it.

        Used by non-MQ scopes (e.g. the creation dialog) that persist an
        ``AgentState`` checkpoint under a client-scoped run id without going
        through the command-event dedup path.
        """
        await asyncio.to_thread(self._ensure_run_sync, run_id, status)

    async def record_step(
        self,
        *,
        run_id: str,
        seq: int,
        kind: str,
        tool: str | None,
        payload: Mapping[str, Any],
    ) -> None:
        await asyncio.to_thread(
            self._record_step_sync, run_id, seq, kind, tool, dict(payload)
        )

    async def finish_run(
        self,
        *,
        run_id: str,
        status: str,
        stop_reason: str | None,
        answer: str | None,
        pending_question: str | None,
    ) -> None:
        await asyncio.to_thread(
            self._finish_run_sync, run_id, status, stop_reason, answer, pending_question
        )

    async def save_checkpoint(self, *, run_id: str, state: AgentState) -> None:
        await asyncio.to_thread(self._save_checkpoint_sync, run_id, state)

    async def load_checkpoint(self, run_id: str) -> AgentState | None:
        return await asyncio.to_thread(self._load_checkpoint_sync, run_id)

    async def count_steps(self, run_id: str) -> int:
        return await asyncio.to_thread(self._count_steps_sync, run_id)

    async def checkpoint_updated_at(self, run_id: str) -> datetime | None:
        """The last time the run's checkpoint ticked — crash-recovery signal."""
        return await asyncio.to_thread(self._checkpoint_updated_at_sync, run_id)

    async def load_run(self, run_id: str) -> AgentRunRecord | None:
        return await asyncio.to_thread(self._load_run_sync, run_id)

    # ── sync bodies ─────────────────────────────────────────────────

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self._database_url, row_factory=dict_row)

    def _migrate_sync(self) -> None:
        migrations = sorted(
            self._migration_directory.glob("V*__*.sql"),
            key=self._migration_number,
        )
        if not migrations:
            raise RuntimeError("agent migration directory is empty")
        with self._connect() as connection:
            connection.execute("SELECT pg_advisory_xact_lock(742019, 13)")
            connection.execute("CREATE SCHEMA IF NOT EXISTS agent")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS agent.agent_schema_migration (
                    version TEXT PRIMARY KEY,
                    checksum CHAR(64) NOT NULL,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            for migration in migrations:
                version = migration.name.split("__", maxsplit=1)[0]
                checksum = hashlib.sha256(migration.read_bytes()).hexdigest()
                existing = connection.execute(
                    """
                    SELECT checksum FROM agent.agent_schema_migration
                    WHERE version = %s
                    """,
                    (version,),
                ).fetchone()
                if existing:
                    if existing["checksum"] != checksum:
                        raise RuntimeError(f"agent migration checksum mismatch: {version}")
                    continue
                connection.execute(migration.read_text(encoding="utf-8"))
                connection.execute(
                    """
                    INSERT INTO agent.agent_schema_migration (version, checksum)
                    VALUES (%s, %s)
                    """,
                    (version, checksum),
                )

    @staticmethod
    def _migration_number(path: Path) -> int:
        return int(path.name[1:].split("__", maxsplit=1)[0])

    def _start_run_sync(
        self,
        run_id: str,
        command_event_id: str | None,
        trip_id: str | None,
    ) -> AgentRunStarted:
        with self._connect() as connection:
            if command_event_id:
                connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 742020))",
                    (command_event_id,),
                )
                existing = connection.execute(
                    "SELECT run_id FROM agent.agent_run WHERE command_event_id = %s",
                    (command_event_id,),
                ).fetchone()
                if existing:
                    return AgentRunStarted(run_id=str(existing["run_id"]), created=False)
            connection.execute(
                """
                INSERT INTO agent.agent_run (run_id, command_event_id, trip_id, status)
                VALUES (%s, %s, %s, 'RUNNING')
                """,
                (run_id, command_event_id, trip_id),
            )
        return AgentRunStarted(run_id=run_id, created=True)

    def _ensure_run_sync(self, run_id: str, status: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO agent.agent_run (run_id, status)
                VALUES (%s, %s)
                ON CONFLICT (run_id) DO NOTHING
                """,
                (run_id, status),
            )

    def _record_step_sync(
        self,
        run_id: str,
        seq: int,
        kind: str,
        tool: str | None,
        payload: dict[str, Any],
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO agent.agent_step (run_id, seq, kind, tool, payload)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (run_id, seq) DO NOTHING
                """,
                (run_id, seq, kind, tool, Jsonb(payload)),
            )

    def _finish_run_sync(
        self,
        run_id: str,
        status: str,
        stop_reason: str | None,
        answer: str | None,
        pending_question: str | None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE agent.agent_run
                SET status = %s,
                    stop_reason = %s,
                    answer = %s,
                    pending_question = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE run_id = %s
                """,
                (status, stop_reason, answer, pending_question, run_id),
            )

    def _save_checkpoint_sync(self, run_id: str, state: AgentState) -> None:
        snapshot = agent_state_to_dict(state)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO agent.agent_checkpoint (run_id, steps, state)
                VALUES (%s, %s, %s)
                ON CONFLICT (run_id) DO UPDATE
                SET steps = EXCLUDED.steps,
                    state = EXCLUDED.state,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (run_id, int(state.steps), Jsonb(snapshot)),
            )

    def _count_steps_sync(self, run_id: str) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS total FROM agent.agent_step WHERE run_id = %s",
                (run_id,),
            ).fetchone()
        return int(row["total"]) if row else 0

    def _load_checkpoint_sync(self, run_id: str) -> AgentState | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT state FROM agent.agent_checkpoint WHERE run_id = %s",
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        return agent_state_from_dict(row["state"])

    def _checkpoint_updated_at_sync(self, run_id: str) -> datetime | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT updated_at FROM agent.agent_checkpoint WHERE run_id = %s",
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        updated_at = row["updated_at"]
        return updated_at if isinstance(updated_at, datetime) else None

    def _load_run_sync(self, run_id: str) -> AgentRunRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT run_id, command_event_id, trip_id, status,
                       stop_reason, answer, pending_question, updated_at
                FROM agent.agent_run
                WHERE run_id = %s
                """,
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        return AgentRunRecord(
            run_id=str(row["run_id"]),
            command_event_id=row["command_event_id"],
            trip_id=row["trip_id"],
            status=row["status"],
            stop_reason=row["stop_reason"],
            answer=row["answer"],
            pending_question=row["pending_question"],
            updated_at=row["updated_at"],
        )


class AgentRunRecorder:
    """Per-run facade between the agent loop and the run repository.

    The P2.1 entry wiring creates one per run and passes :meth:`on_state` as
    ``run_agent``'s ``checkpoint_sink``: new observations are appended to the
    trajectory and every streamed state leaves a restorable checkpoint
    behind.
    """

    def __init__(
        self,
        repository: PsycopgAgentRunRepository,
        *,
        run_id: str,
        command_event_id: str | None = None,
        trip_id: str | None = None,
        initial_seq: int = 0,
    ) -> None:
        self._repository = repository
        self._run_id = run_id
        self._command_event_id = command_event_id
        self._trip_id = trip_id
        self._started = False
        self._seen_observations = 0
        self._seq = initial_seq
        self.created = False

    async def start(self) -> AgentRunStarted:
        started = await self._repository.start_run(
            run_id=self._run_id,
            command_event_id=self._command_event_id,
            trip_id=self._trip_id,
        )
        self._started = True
        self.created = started.created
        if not started.created:
            logger.info(
                "agent_run_deduplicated run_id=%s command_event_id=%s",
                started.run_id,
                self._command_event_id,
            )
        return started

    async def resume_existing(self) -> None:
        """Mark an existing run as resumed without inserting a new run row."""
        self._started = True

    async def on_state(self, state: AgentState) -> None:
        if not self._started:
            raise RuntimeError("AgentRunRecorder.start must run before on_state")
        for observation in state.observations[self._seen_observations :]:
            await self._repository.record_step(
                run_id=self._run_id,
                seq=self._seq,
                kind="TOOL_OBSERVATION",
                tool=observation.tool,
                payload={
                    "ok": observation.ok,
                    "summary": observation.summary,
                    "error_code": observation.error_code,
                },
            )
            self._seq += 1
        self._seen_observations = len(state.observations)
        await self._repository.save_checkpoint(run_id=self._run_id, state=state)

    async def finish(self, result: AgentRunResult) -> None:
        await self._repository.finish_run(
            run_id=self._run_id,
            status=status_for_stop_reason(result.stop_reason),
            stop_reason=result.stop_reason,
            answer=result.answer,
            pending_question=result.pending_question,
        )
