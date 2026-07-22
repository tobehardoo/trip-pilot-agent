"""PostgreSQL persistence for acquisition resources, candidates, and runs."""

import asyncio
import hashlib
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from trip_agent.acquisition.fetch_models import FetchValidators
from trip_agent.acquisition.recording import (
    AcquisitionPersisted,
    AcquisitionRecord,
    ConditionalResourceState,
    SnapshotId,
)
from trip_agent.acquisition.scheduling import FetchAttempt, FetchAttemptFailed


class PsycopgAcquisitionRepository:
    """Persist one complete acquisition execution in a single transaction."""

    _migration_directory = Path(__file__).with_name("migrations")

    def __init__(self, database_url: str) -> None:
        if not database_url.strip():
            raise ValueError("acquisition database URL cannot be empty")
        self._database_url = database_url.strip()

    async def migrate(self) -> None:
        await asyncio.to_thread(self._migrate_sync)

    async def record(self, record: AcquisitionRecord) -> AcquisitionPersisted:
        return await asyncio.to_thread(self._record_sync, record)

    async def get_conditional_state(
        self,
        resource_id: str,
    ) -> ConditionalResourceState | None:
        return await asyncio.to_thread(self._get_conditional_state_sync, resource_id)

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self._database_url, row_factory=dict_row)

    def _migrate_sync(self) -> None:
        migrations = sorted(
            self._migration_directory.glob("V*__*.sql"),
            key=self._migration_number,
        )
        if not migrations:
            raise RuntimeError("acquisition migration directory is empty")

        with self._connect() as connection:
            connection.execute("SELECT pg_advisory_xact_lock(742019, 12)")
            connection.execute("CREATE SCHEMA IF NOT EXISTS agent")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS agent.acquisition_schema_migration (
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
                    SELECT checksum FROM agent.acquisition_schema_migration
                    WHERE version = %s
                    """,
                    (version,),
                ).fetchone()
                if existing:
                    if existing["checksum"] != checksum:
                        raise RuntimeError(f"acquisition migration checksum mismatch: {version}")
                    continue
                connection.execute(migration.read_text(encoding="utf-8"))
                connection.execute(
                    """
                    INSERT INTO agent.acquisition_schema_migration (version, checksum)
                    VALUES (%s, %s)
                    """,
                    (version, checksum),
                )

    def _record_sync(self, record: AcquisitionRecord) -> AcquisitionPersisted:
        resource = record.resource
        with self._connect() as connection:
            self._upsert_resource_attempt(connection, record)
            snapshot_id, snapshot_created = self._save_snapshot(
                connection,
                record,
            )
            self._update_verified_resource(connection, record)
            self._save_run(connection, record, snapshot_id)
        return AcquisitionPersisted(
            resource_id=resource.resource_id,
            run_id=record.run.run_id,
            snapshot_id=snapshot_id,
            snapshot_created=snapshot_created,
        )

    @staticmethod
    def _upsert_resource_attempt(
        connection: psycopg.Connection,
        record: AcquisitionRecord,
    ) -> None:
        resource = record.resource
        connection.execute(
            """
            INSERT INTO agent.knowledge_resource (
                resource_id, source_id, city, source_url, final_url,
                etag, last_modified, last_attempted_at, last_verified_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (resource_id) DO UPDATE SET
                last_attempted_at = GREATEST(
                    agent.knowledge_resource.last_attempted_at,
                    EXCLUDED.last_attempted_at
                ),
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                resource.resource_id,
                resource.source_id,
                resource.city,
                resource.source_url,
                resource.final_url,
                None,
                None,
                resource.last_attempted_at,
                None,
            ),
        )
    @staticmethod
    def _update_verified_resource(
        connection: psycopg.Connection,
        record: AcquisitionRecord,
    ) -> None:
        resource = record.resource
        if resource.last_verified_at is None or resource.validators is None:
            return
        content_hash = resource.current_content_hash
        connection.execute(
            """
            UPDATE agent.knowledge_resource
            SET final_url = %s,
                etag = %s,
                last_modified = %s,
                last_changed_at = CASE
                    WHEN %s::text IS NOT NULL
                     AND current_content_hash IS DISTINCT FROM %s::text
                    THEN %s
                    ELSE last_changed_at
                END,
                current_content_hash = COALESCE(%s::text, current_content_hash),
                last_verified_at = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE resource_id = %s
              AND (last_verified_at IS NULL OR %s >= last_verified_at)
            """,
            (
                resource.final_url,
                resource.validators.etag,
                resource.validators.last_modified,
                content_hash,
                content_hash,
                resource.last_verified_at,
                content_hash,
                resource.last_verified_at,
                resource.resource_id,
                resource.last_verified_at,
            ),
        )
        connection.execute(
            """
            UPDATE agent.knowledge_resource
            SET last_changed_at = last_verified_at,
                updated_at = CURRENT_TIMESTAMP
            WHERE resource_id = %s
              AND %s < last_verified_at
              AND %s > COALESCE(last_changed_at, '-infinity'::timestamptz)
              AND current_content_hash IS DISTINCT FROM %s::text
            """,
            (
                resource.resource_id,
                resource.last_verified_at,
                resource.last_verified_at,
                content_hash,
            ),
        )

    @staticmethod
    def _save_snapshot(
        connection: psycopg.Connection,
        record: AcquisitionRecord,
    ) -> tuple[SnapshotId | None, bool]:
        snapshot = record.snapshot
        if snapshot is None:
            return None, False
        inserted = connection.execute(
            """
            INSERT INTO agent.knowledge_snapshot (
                snapshot_id, resource_id, source_url, final_url, fetched_at,
                published_at, content_hash, raw_content, content_type, etag,
                last_modified, parser_version, review_status
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (resource_id, content_hash, parser_version) DO NOTHING
            RETURNING snapshot_id
            """,
            (
                snapshot.snapshot_id,
                snapshot.resource_id,
                snapshot.source_url,
                snapshot.final_url,
                snapshot.fetched_at,
                snapshot.published_at,
                snapshot.content_hash,
                snapshot.raw_content,
                snapshot.content_type,
                snapshot.validators.etag,
                snapshot.validators.last_modified,
                snapshot.parser_version,
                snapshot.review_status,
            ),
        ).fetchone()
        if inserted is not None:
            return SnapshotId(inserted["snapshot_id"]), True
        existing = connection.execute(
            """
            SELECT snapshot_id FROM agent.knowledge_snapshot
            WHERE resource_id = %s AND content_hash = %s AND parser_version = %s
            """,
            (snapshot.resource_id, snapshot.content_hash, snapshot.parser_version),
        ).fetchone()
        if existing is None:
            raise RuntimeError("candidate snapshot conflict could not be resolved")
        return SnapshotId(existing["snapshot_id"]), False

    def _get_conditional_state_sync(
        self,
        resource_id: str,
    ) -> ConditionalResourceState | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT etag, last_modified, current_content_hash
                FROM agent.knowledge_resource
                WHERE resource_id = %s
                  AND last_verified_at IS NOT NULL
                  AND current_content_hash IS NOT NULL
                """,
                (resource_id,),
            ).fetchone()
        if row is None or (row["etag"] is None and row["last_modified"] is None):
            return None
        return ConditionalResourceState(
            validators=FetchValidators(etag=row["etag"], last_modified=row["last_modified"]),
            content_hash=row["current_content_hash"],
        )

    @staticmethod
    def _save_run(
        connection: psycopg.Connection,
        record: AcquisitionRecord,
        snapshot_id: SnapshotId | None,
    ) -> None:
        run = record.run
        if run.snapshot_id is not None and snapshot_id is None:
            raise RuntimeError("fetched run must reference a persisted snapshot")
        connection.execute(
            """
            INSERT INTO agent.knowledge_fetch_run (
                run_id, resource_id, started_at, completed_at, status,
                attempt_count, attempts, snapshot_id, error_code, error_message,
                retryable, http_status
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                run.run_id,
                run.resource_id,
                run.started_at,
                run.completed_at,
                run.status,
                run.attempt_count,
                Jsonb([_serialize_attempt(attempt) for attempt in run.attempts]),
                snapshot_id,
                run.error_code,
                run.error_message,
                run.retryable,
                run.http_status,
            ),
        )

    @staticmethod
    def _migration_number(path: Path) -> int:
        version = path.name.split("__", maxsplit=1)[0]
        number = version.removeprefix("V")
        if not number.isdigit():
            raise RuntimeError(f"invalid acquisition migration filename: {path.name}")
        return int(number)


def _serialize_attempt(attempt: FetchAttempt) -> dict[str, object]:
    values: dict[str, object] = {
        "status": attempt.status,
        "attempt_number": attempt.attempt_number,
        "started_at": _iso_utc(attempt.started_at),
        "completed_at": _iso_utc(attempt.completed_at),
    }
    if isinstance(attempt, FetchAttemptFailed):
        values.update(
            error_code=attempt.error_code,
            message=attempt.message,
            retryable=attempt.retryable,
            status_code=attempt.status_code,
        )
    return values


def _iso_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
