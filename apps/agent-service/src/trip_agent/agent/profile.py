"""P3.2: cross-session user travel profile (confirmed preferences only).

The trust model mirrors the constraint slots: the model may only PROPOSE a
preference (it lands as ``PENDING`` and never influences decisions); a
preference becomes ``CONFIRMED`` through the user's own words and ``REVOKED``
by an explicit negation.  A revoked preference never revives by re-proposal.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

import psycopg
from psycopg.rows import dict_row

PROFILE_CATEGORIES: frozenset[str] = frozenset(
    {"PACE", "BUDGET", "MOBILITY", "DIETARY", "AVOID", "TRANSPORT", "ACCOMMODATION"}
)

ProfileStatus = Literal["PENDING", "CONFIRMED", "REVOKED"]


@dataclass(frozen=True, slots=True)
class PreferenceRecord:
    user_id: str
    category: str
    value: str
    status: str
    updated_at: datetime | None = None


class TravelProfileRepository:
    """PostgreSQL store for cross-session travel preferences."""

    def __init__(self, database_url: str) -> None:
        if not database_url.strip():
            raise ValueError("profile database URL cannot be empty")
        self._database_url = database_url.strip()

    async def migrate(self) -> None:
        # The agent migration directory is shared with the run repository;
        # V2 (this table) rides the same checksummed runner.
        from trip_agent.agent.persistence import PsycopgAgentRunRepository

        await PsycopgAgentRunRepository(self._database_url).migrate()

    async def propose(
        self,
        *,
        user_id: str,
        category: str,
        value: str,
    ) -> PreferenceRecord:
        """Record a model proposal as PENDING; an existing row is untouched."""
        return await asyncio.to_thread(
            self._propose_sync, user_id, category, value
        )

    async def confirm(
        self, *, user_id: str, category: str, value: str
    ) -> PreferenceRecord | None:
        """Confirm an existing preference; a REVOKED one refuses."""
        return await asyncio.to_thread(
            self._set_status_sync, user_id, category, value, "CONFIRMED", allow_from_revoked=False
        )

    async def revoke(
        self, *, user_id: str, category: str, value: str
    ) -> PreferenceRecord | None:
        return await asyncio.to_thread(
            self._set_status_sync, user_id, category, value, "REVOKED", allow_from_revoked=True
        )

    async def list_confirmed(self, user_id: str) -> tuple[PreferenceRecord, ...]:
        return await asyncio.to_thread(self._list_confirmed_sync, user_id)

    # ── sync bodies ─────────────────────────────────────────────────

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self._database_url, row_factory=dict_row)

    def _propose_sync(self, user_id: str, category: str, value: str) -> PreferenceRecord:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO agent.user_travel_profile (user_id, category, value, status)
                VALUES (%s, %s, %s, 'PENDING')
                ON CONFLICT (user_id, category, value) DO NOTHING
                """,
                (user_id, category, value),
            )
            row = connection.execute(
                """
                SELECT user_id, category, value, status, updated_at
                FROM agent.user_travel_profile
                WHERE user_id = %s AND category = %s AND value = %s
                """,
                (user_id, category, value),
            ).fetchone()
        assert row is not None
        return PreferenceRecord(
            user_id=str(row["user_id"]),
            category=row["category"],
            value=row["value"],
            status=row["status"],
            updated_at=row["updated_at"],
        )

    def _set_status_sync(
        self,
        user_id: str,
        category: str,
        value: str,
        status: str,
        *,
        allow_from_revoked: bool,
    ) -> PreferenceRecord | None:
        with self._connect() as connection:
            guard = "" if allow_from_revoked else "AND status <> 'REVOKED'"
            row = connection.execute(
                f"""
                UPDATE agent.user_travel_profile
                SET status = %s, updated_at = CURRENT_TIMESTAMP
                WHERE user_id = %s AND category = %s AND value = %s {guard}
                RETURNING user_id, category, value, status, updated_at
                """,
                (status, user_id, category, value),
            ).fetchone()
        if row is None:
            return None
        return PreferenceRecord(
            user_id=str(row["user_id"]),
            category=row["category"],
            value=row["value"],
            status=row["status"],
            updated_at=row["updated_at"],
        )

    def _list_confirmed_sync(self, user_id: str) -> tuple[PreferenceRecord, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT user_id, category, value, status, updated_at
                FROM agent.user_travel_profile
                WHERE user_id = %s AND status = 'CONFIRMED'
                ORDER BY category, value
                """,
                (user_id,),
            ).fetchall()
        return tuple(
            PreferenceRecord(
                user_id=str(row["user_id"]),
                category=row["category"],
                value=row["value"],
                status=row["status"],
                updated_at=row["updated_at"],
            )
            for row in rows
        )
