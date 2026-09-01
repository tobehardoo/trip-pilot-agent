"""PostgreSQL persistence for acquisition resources, candidates, and runs."""

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from trip_agent.acquisition.extraction import ExtractionQualityIssue
from trip_agent.acquisition.extraction_service import (
    ExtractionPersisted,
    ExtractionVersionConflict,
    PendingSnapshot,
    SnapshotExtractionRecord,
)
from trip_agent.acquisition.fetch_models import FetchValidators
from trip_agent.acquisition.freshness import ResourceFreshnessState
from trip_agent.acquisition.recording import (
    AcquisitionPersisted,
    AcquisitionRecord,
    ConditionalResourceState,
    SnapshotId,
)
from trip_agent.acquisition.review import (
    PendingReviewCandidate,
    PublicationClaim,
    PublicationClaimResult,
    PublishedKnowledge,
    ReviewAction,
    ReviewPersistence,
    ReviewStateConflict,
)
from trip_agent.acquisition.scheduling import FetchAttempt, FetchAttemptFailed
from trip_agent.retrieval.service import KnowledgeImportResult


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

    async def list_snapshots_pending_extraction(
        self,
        *,
        parser_version: str,
        limit: int,
    ) -> tuple[PendingSnapshot, ...]:
        return await asyncio.to_thread(
            self._list_snapshots_pending_extraction_sync,
            parser_version,
            limit,
        )

    async def save_extraction(self, record: SnapshotExtractionRecord) -> ExtractionPersisted:
        return await asyncio.to_thread(self._save_extraction_sync, record)

    async def save_review_action(self, action: ReviewAction) -> ReviewPersistence:
        return await asyncio.to_thread(self._save_review_action_sync, action)

    async def list_resource_freshness(self) -> tuple[ResourceFreshnessState, ...]:
        return await asyncio.to_thread(self._list_resource_freshness_sync)

    async def list_reviews_pending(
        self,
        *,
        limit: int,
    ) -> tuple[PendingReviewCandidate, ...]:
        return await asyncio.to_thread(self._list_reviews_pending_sync, limit)

    async def claim_publication(
        self,
        *,
        review_action_id: str,
        claim_timeout: timedelta,
    ) -> PublicationClaimResult:
        return await asyncio.to_thread(
            self._claim_publication_sync,
            review_action_id,
            claim_timeout,
        )

    async def mark_publication_succeeded(
        self,
        *,
        review_action_id: str,
        claim_token: int,
        result: KnowledgeImportResult,
        published_at: datetime,
    ) -> None:
        await asyncio.to_thread(
            self._mark_publication_succeeded_sync,
            review_action_id,
            claim_token,
            result,
            published_at,
        )

    async def mark_publication_failed(
        self,
        *,
        review_action_id: str,
        claim_token: int,
        error: str,
        failed_at: datetime,
    ) -> None:
        await asyncio.to_thread(
            self._mark_publication_failed_sync,
            review_action_id,
            claim_token,
            error,
            failed_at,
        )

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
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 742019))",
                (resource.resource_id,),
            )
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
                resource_id, source_id, source_name, reliability_level, city, source_url, final_url,
                etag, last_modified, last_attempted_at, last_verified_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (resource_id) DO UPDATE SET
                source_name = EXCLUDED.source_name,
                reliability_level = EXCLUDED.reliability_level,
                last_attempted_at = GREATEST(
                    agent.knowledge_resource.last_attempted_at,
                    EXCLUDED.last_attempted_at
                ),
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                resource.resource_id,
                resource.source_id,
                resource.source_name,
                resource.reliability_level,
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

    def _list_snapshots_pending_extraction_sync(
        self,
        parser_version: str,
        limit: int,
    ) -> tuple[PendingSnapshot, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT s.snapshot_id, s.raw_content, s.content_type, s.fetched_at
                FROM agent.knowledge_snapshot s
                WHERE s.review_status = 'PENDING'
                  AND NOT EXISTS (
                    SELECT 1 FROM agent.knowledge_extraction e
                    WHERE e.snapshot_id = s.snapshot_id AND e.parser_version = %s
                  )
                ORDER BY s.fetched_at, s.snapshot_id
                LIMIT %s
                """,
                (parser_version, limit),
            ).fetchall()
        return tuple(PendingSnapshot(**row) for row in rows)

    def _save_extraction_sync(
        self,
        record: SnapshotExtractionRecord,
    ) -> ExtractionPersisted:
        issues = [
            {"code": issue.code, "severity": issue.severity, "message": issue.message}
            for issue in record.issues
        ]
        with self._connect() as connection:
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 742020))",
                (record.extraction_id,),
            )
            inserted = connection.execute(
                """
                INSERT INTO agent.knowledge_extraction (
                    extraction_id, snapshot_id, parser_version, status, title, content,
                    content_hash, published_at, content_source, quality_issues,
                    result_fingerprint, extracted_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (snapshot_id, parser_version) DO NOTHING
                RETURNING extraction_id
                """,
                (
                    record.extraction_id,
                    record.snapshot_id,
                    record.parser_version,
                    record.status,
                    record.title,
                    record.content,
                    record.content_hash,
                    record.published_at,
                    record.content_source,
                    Jsonb(issues),
                    record.result_fingerprint,
                    record.extracted_at,
                ),
            ).fetchone()
            status: Literal["created", "unchanged"] = "created"
            extraction_id = record.extraction_id
            if inserted is None:
                existing = connection.execute(
                    """
                    SELECT extraction_id, result_fingerprint
                    FROM agent.knowledge_extraction
                    WHERE snapshot_id = %s AND parser_version = %s
                    """,
                    (record.snapshot_id, record.parser_version),
                ).fetchone()
                if existing is None or existing["result_fingerprint"] != record.result_fingerprint:
                    raise ExtractionVersionConflict(
                        f"snapshot {record.snapshot_id} parser {record.parser_version} is immutable"
                    )
                status = "unchanged"
                extraction_id = existing["extraction_id"]
        return ExtractionPersisted(
            extraction_id=extraction_id,
            snapshot_id=record.snapshot_id,
            status=status,
        )

    def _save_review_action_sync(self, action: ReviewAction) -> ReviewPersistence:
        with self._connect() as connection:
            if action.action == "WITHDRAW":
                return self._save_withdrawal(connection, action)
            return self._save_initial_review(connection, action)

    def _list_resource_freshness_sync(self) -> tuple[ResourceFreshnessState, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT r.resource_id, r.source_id, r.source_url,
                    r.last_attempted_at, r.last_verified_at, r.last_changed_at,
                    latest.status AS latest_run_status,
                    latest.error_code AS latest_error_code,
                    latest.error_message AS latest_error_message
                FROM agent.knowledge_resource r
                LEFT JOIN LATERAL (
                    SELECT run.status, run.error_code, run.error_message
                    FROM agent.knowledge_fetch_run run
                    WHERE run.resource_id = r.resource_id
                    ORDER BY run.completed_at DESC, run.run_id DESC
                    LIMIT 1
                ) latest ON TRUE
                ORDER BY r.source_id, r.source_url
                """
            ).fetchall()
        return tuple(ResourceFreshnessState(**row) for row in rows)

    def _list_reviews_pending_sync(self, limit: int) -> tuple[PendingReviewCandidate, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT e.extraction_id, e.snapshot_id, r.city,
                    s.source_url, r.source_name, e.title, e.content,
                    e.published_at, s.fetched_at, e.extracted_at, e.quality_issues
                FROM agent.knowledge_extraction e
                JOIN agent.knowledge_snapshot s ON s.snapshot_id = e.snapshot_id
                JOIN agent.knowledge_resource r ON r.resource_id = s.resource_id
                WHERE e.status = 'EXTRACTED'
                  AND s.review_status = 'PENDING'
                  AND r.source_name IS NOT NULL
                  AND r.reliability_level IS NOT NULL
                ORDER BY e.extracted_at, e.extraction_id
                LIMIT %s
                """,
                (limit,),
            ).fetchall()
        return tuple(
            PendingReviewCandidate(
                extraction_id=row["extraction_id"],
                snapshot_id=row["snapshot_id"],
                city=row["city"],
                source_url=row["source_url"],
                source_name=row["source_name"],
                title=row["title"],
                content=row["content"],
                published_at=row["published_at"],
                fetched_at=row["fetched_at"],
                extracted_at=row["extracted_at"],
                quality_issues=tuple(
                    ExtractionQualityIssue(**issue) for issue in row["quality_issues"]
                ),
            )
            for row in rows
        )

    @staticmethod
    def _save_initial_review(
        connection: psycopg.Connection,
        action: ReviewAction,
    ) -> ReviewPersistence:
        candidate = connection.execute(
            """
            SELECT e.status AS extraction_status, e.snapshot_id,
                s.review_status, s.resource_id,
                r.city, r.source_name, r.reliability_level
            FROM agent.knowledge_extraction e
            JOIN agent.knowledge_snapshot s ON s.snapshot_id = e.snapshot_id
            JOIN agent.knowledge_resource r ON r.resource_id = s.resource_id
            WHERE e.extraction_id = %s
            FOR UPDATE OF s, r
            """,
            (action.extraction_id,),
        ).fetchone()
        if candidate is None or candidate["extraction_status"] != "EXTRACTED":
            raise ReviewStateConflict("extraction is not eligible for human review")
        if candidate["source_name"] is None or candidate["reliability_level"] is None:
            raise ReviewStateConflict("source metadata is incomplete; reacquire the resource")
        if candidate["review_status"] == "WITHDRAWN":
            raise ReviewStateConflict("candidate approval has been withdrawn")
        if candidate["review_status"] != "PENDING":
            return PsycopgAcquisitionRepository._existing_review_result(
                connection,
                snapshot_id=candidate["snapshot_id"],
                action=action,
            )

        document_id: str | None = None
        document_version: int | None = None
        document_city: str | None = None
        document_source_name: str | None = None
        document_reliability_level: str | None = None
        review_status: Literal["APPROVED", "REJECTED"]
        if action.action == "APPROVE":
            document_id = f"acquired-{candidate['resource_id']}"
            document_version = connection.execute(
                """
                SELECT COALESCE(MAX(a.document_version), 0) + 1 AS next_version
                FROM agent.knowledge_review_action a
                JOIN agent.knowledge_snapshot reviewed
                    ON reviewed.snapshot_id = a.snapshot_id
                WHERE reviewed.resource_id = %s AND a.action = 'APPROVE'
                """,
                (candidate["resource_id"],),
            ).fetchone()["next_version"]
            document_city = candidate["city"]
            document_source_name = candidate["source_name"]
            document_reliability_level = candidate["reliability_level"]
            review_status = "APPROVED"
        else:
            review_status = "REJECTED"

        connection.execute(
            """
            INSERT INTO agent.knowledge_review_action (
                action_id, snapshot_id, extraction_id, action, parent_action_id,
                reviewer_id, note, reviewed_at, decision_fingerprint,
                category, valid_from, valid_to, applicable_seasons, traveler_types,
                document_id, document_version, document_city, document_source_name,
                document_reliability_level
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                action.action_id,
                candidate["snapshot_id"],
                action.extraction_id,
                action.action,
                None,
                action.reviewer_id,
                action.note,
                action.reviewed_at,
                action.decision_fingerprint,
                action.category,
                action.valid_from,
                action.valid_to,
                list(action.applicable_seasons),
                list(action.traveler_types),
                document_id,
                document_version,
                document_city,
                document_source_name,
                document_reliability_level,
            ),
        )
        updated = connection.execute(
            """
            UPDATE agent.knowledge_snapshot
            SET review_status = %s
            WHERE snapshot_id = %s AND review_status = 'PENDING'
            """,
            (review_status, candidate["snapshot_id"]),
        )
        if updated.rowcount != 1:
            raise ReviewStateConflict("candidate review state changed concurrently")
        if action.action == "APPROVE":
            connection.execute(
                """
                INSERT INTO agent.knowledge_publication (review_action_id, status)
                VALUES (%s, 'PENDING')
                """,
                (action.action_id,),
            )
        return ReviewPersistence(
            action_id=action.action_id,
            snapshot_id=candidate["snapshot_id"],
            review_status=review_status,
            persistence_status="created",
            document_id=document_id,
            document_version=document_version,
        )

    @staticmethod
    def _existing_review_result(
        connection: psycopg.Connection,
        *,
        snapshot_id: str,
        action: ReviewAction,
    ) -> ReviewPersistence:
        existing = connection.execute(
            """
            SELECT action_id, action, decision_fingerprint, document_id, document_version
            FROM agent.knowledge_review_action
            WHERE snapshot_id = %s AND action IN ('APPROVE', 'REJECT')
            """,
            (snapshot_id,),
        ).fetchone()
        if (
            existing is None
            or existing["action"] != action.action
            or existing["decision_fingerprint"] != action.decision_fingerprint
        ):
            raise ReviewStateConflict("candidate already has a different review decision")
        review_status: Literal["APPROVED", "REJECTED"] = (
            "APPROVED" if existing["action"] == "APPROVE" else "REJECTED"
        )
        return ReviewPersistence(
            action_id=existing["action_id"],
            snapshot_id=snapshot_id,
            review_status=review_status,
            persistence_status="unchanged",
            document_id=existing["document_id"],
            document_version=existing["document_version"],
        )

    @staticmethod
    def _save_withdrawal(
        connection: psycopg.Connection,
        action: ReviewAction,
    ) -> ReviewPersistence:
        approval = connection.execute(
            """
            SELECT a.snapshot_id, a.document_id, a.document_version, s.review_status
            FROM agent.knowledge_review_action a
            JOIN agent.knowledge_snapshot s ON s.snapshot_id = a.snapshot_id
            WHERE a.action_id = %s AND a.action = 'APPROVE'
            FOR UPDATE OF s
            """,
            (action.parent_action_id,),
        ).fetchone()
        if approval is None:
            raise ReviewStateConflict("approval action does not exist")
        if approval["review_status"] == "WITHDRAWN":
            existing = connection.execute(
                """
                SELECT action_id, decision_fingerprint
                FROM agent.knowledge_review_action
                WHERE parent_action_id = %s AND action = 'WITHDRAW'
                """,
                (action.parent_action_id,),
            ).fetchone()
            if existing and existing["decision_fingerprint"] == action.decision_fingerprint:
                return ReviewPersistence(
                    action_id=existing["action_id"],
                    snapshot_id=approval["snapshot_id"],
                    review_status="WITHDRAWN",
                    persistence_status="unchanged",
                )
            raise ReviewStateConflict("approval already has a different withdrawal")
        if approval["review_status"] != "APPROVED":
            raise ReviewStateConflict("approval is not withdrawable")

        publication = connection.execute(
            """
            SELECT status, attempt_count FROM agent.knowledge_publication
            WHERE review_action_id = %s
            FOR UPDATE
            """,
            (action.parent_action_id,),
        ).fetchone()
        if publication is None:
            raise ReviewStateConflict("approval publication record is missing")
        if publication["status"] == "PUBLISHING":
            raise ReviewStateConflict("publication is in progress")
        if publication["status"] == "PUBLISHED":
            raise ReviewStateConflict("published knowledge cannot be withdrawn")
        if publication["status"] == "CANCELLED":
            raise ReviewStateConflict("approval publication is already cancelled")
        if publication["status"] != "PENDING" or publication["attempt_count"] != 0:
            raise ReviewStateConflict("publication was already attempted")

        connection.execute(
            """
            INSERT INTO agent.knowledge_review_action (
                action_id, snapshot_id, action, parent_action_id, reviewer_id,
                note, reviewed_at, decision_fingerprint
            ) VALUES (%s, %s, 'WITHDRAW', %s, %s, %s, %s, %s)
            """,
            (
                action.action_id,
                approval["snapshot_id"],
                action.parent_action_id,
                action.reviewer_id,
                action.note,
                action.reviewed_at,
                action.decision_fingerprint,
            ),
        )
        connection.execute(
            """
            UPDATE agent.knowledge_snapshot SET review_status = 'WITHDRAWN'
            WHERE snapshot_id = %s
            """,
            (approval["snapshot_id"],),
        )
        connection.execute(
            """
            UPDATE agent.knowledge_publication
            SET status = 'CANCELLED', claim_started_at = NULL,
                published_at = NULL, failed_at = NULL, last_error = NULL,
                chunk_count = NULL, importer_status = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE review_action_id = %s
            """,
            (action.parent_action_id,),
        )
        return ReviewPersistence(
            action_id=action.action_id,
            snapshot_id=approval["snapshot_id"],
            review_status="WITHDRAWN",
            persistence_status="created",
        )

    def _claim_publication_sync(
        self,
        review_action_id: str,
        claim_timeout: timedelta,
    ) -> PublicationClaimResult:
        with self._connect() as connection:
            approval = connection.execute(
                """
                SELECT a.snapshot_id, a.document_id, a.document_version,
                    a.document_city, a.document_source_name,
                    a.document_reliability_level, a.category,
                    a.valid_from, a.valid_to, a.applicable_seasons, a.traveler_types,
                    s.review_status, s.source_url, s.fetched_at,
                    e.title, e.content, e.content_hash, e.published_at
                FROM agent.knowledge_review_action a
                JOIN agent.knowledge_snapshot s ON s.snapshot_id = a.snapshot_id
                JOIN agent.knowledge_extraction e ON e.extraction_id = a.extraction_id
                WHERE a.action_id = %s AND a.action = 'APPROVE'
                FOR UPDATE OF s
                """,
                (review_action_id,),
            ).fetchone()
            if approval is None:
                return None
            publication = connection.execute(
                """
                SELECT status, attempt_count, claim_started_at,
                    chunk_count, importer_status
                FROM agent.knowledge_publication
                WHERE review_action_id = %s
                FOR UPDATE
                """,
                (review_action_id,),
            ).fetchone()
            if publication is None:
                return None
            if publication["status"] == "PUBLISHED":
                return PublishedKnowledge(
                    review_action_id=review_action_id,
                    document_id=approval["document_id"],
                    document_version=approval["document_version"],
                    chunk_count=publication["chunk_count"],
                    importer_status=publication["importer_status"],
                )
            if approval["review_status"] != "APPROVED":
                return None
            if publication["status"] not in {"PENDING", "FAILED", "PUBLISHING"}:
                return None

            claimed = connection.execute(
                """
                UPDATE agent.knowledge_publication
                SET status = 'PUBLISHING',
                    attempt_count = attempt_count + 1,
                    claim_started_at = CURRENT_TIMESTAMP,
                    failed_at = NULL,
                    last_error = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE review_action_id = %s
                  AND (
                    status IN ('PENDING', 'FAILED')
                    OR (status = 'PUBLISHING'
                        AND claim_started_at <= CURRENT_TIMESTAMP - %s)
                  )
                RETURNING attempt_count
                """,
                (review_action_id, claim_timeout),
            ).fetchone()
            if claimed is None:
                return None
            return PublicationClaim(
                review_action_id=review_action_id,
                claim_token=claimed["attempt_count"],
                document_id=approval["document_id"],
                document_version=approval["document_version"],
                city=approval["document_city"],
                category=approval["category"],
                title=approval["title"],
                content=approval["content"],
                content_hash=approval["content_hash"],
                source_url=approval["source_url"],
                source_name=approval["document_source_name"],
                reliability_level=approval["document_reliability_level"],
                published_at=approval["published_at"],
                collected_at=approval["fetched_at"],
                valid_from=approval["valid_from"],
                valid_to=approval["valid_to"],
                applicable_seasons=tuple(approval["applicable_seasons"]),
                traveler_types=tuple(approval["traveler_types"]),
            )

    def _mark_publication_succeeded_sync(
        self,
        review_action_id: str,
        claim_token: int,
        result: KnowledgeImportResult,
        published_at: datetime,
    ) -> None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT p.status, p.attempt_count, a.document_id, a.document_version
                FROM agent.knowledge_publication p
                JOIN agent.knowledge_review_action a
                    ON a.action_id = p.review_action_id
                WHERE p.review_action_id = %s
                FOR UPDATE OF p
                """,
                (review_action_id,),
            ).fetchone()
            if row is None:
                raise ReviewStateConflict("publication record does not exist")
            if (
                row["document_id"] != result.document_id
                or row["document_version"] != result.version
            ):
                raise ReviewStateConflict("import result does not match approved document")
            if row["status"] == "PUBLISHED":
                return
            if (
                row["status"] not in {"PUBLISHING", "FAILED"}
                or not 1 <= claim_token <= row["attempt_count"]
            ):
                raise ReviewStateConflict("publication claim is no longer active")
            connection.execute(
                """
                UPDATE agent.knowledge_publication
                SET status = 'PUBLISHED', claim_started_at = NULL,
                    published_at = %s, failed_at = NULL, last_error = NULL,
                    chunk_count = %s, importer_status = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE review_action_id = %s
                """,
                (
                    published_at,
                    result.chunk_count,
                    result.status,
                    review_action_id,
                ),
            )

    def _mark_publication_failed_sync(
        self,
        review_action_id: str,
        claim_token: int,
        error: str,
        failed_at: datetime,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE agent.knowledge_publication
                SET status = 'FAILED', claim_started_at = NULL,
                    failed_at = %s, last_error = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE review_action_id = %s
                  AND status = 'PUBLISHING'
                  AND attempt_count = %s
                """,
                (failed_at, error, review_action_id, claim_token),
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
