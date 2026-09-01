"""P3.2: cross-session travel profile — propose/confirm/revoke semantics.

Tool-level tests use a fake store; SQL integration tests are gated on
``KNOWLEDGE_TEST_DATABASE_URL`` like the rest of the repository suite.  The
trust rule mirrors the constraint slots: confirmation requires the value in
the user's verbatim evidence, and revoked preferences never revive.
"""

from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from typing import Any

import psycopg
import pytest

from trip_agent.agent import AgentState, ToolCall, ToolRegistry, ToolRuntime
from trip_agent.agent.profile import TravelProfileRepository
from trip_agent.platform_util import run_async


class FakeProfileStore:
    def __init__(self) -> None:
        self.rows: dict[tuple[str, str, str], str] = {}

    async def propose(self, *, user_id: str, category: str, value: str) -> Any:
        self.rows.setdefault((user_id, category, value), "PENDING")
        return SimpleNamespace(status=self.rows[(user_id, category, value)])

    async def confirm(self, *, user_id: str, category: str, value: str) -> Any:
        status = self.rows.get((user_id, category, value))
        if status is None or status == "REVOKED":
            return None
        self.rows[(user_id, category, value)] = "CONFIRMED"
        return SimpleNamespace(status="CONFIRMED")

    async def revoke(self, *, user_id: str, category: str, value: str) -> Any:
        self.rows[(user_id, category, value)] = "REVOKED"
        return SimpleNamespace(status="REVOKED")

    async def list_confirmed(self, user_id: str) -> list[Any]:
        return [
            SimpleNamespace(category=category, value=value)
            for (uid, category, value), status in self.rows.items()
            if uid == user_id and status == "CONFIRMED"
        ]


def _tools(store: Any) -> ToolRegistry:
    return ToolRegistry.with_runtime(ToolRuntime(profile_store=store))


def _state(user_id: str | None = "user-1") -> AgentState:
    return AgentState(user_id=user_id)


def test_propose_lands_as_pending() -> None:
    store = FakeProfileStore()
    result, _ = run_async(
        _tools(store).invoke(
            ToolCall(
                "update_preferences",
                {"proposals": [{"category": "PACE", "value": "松弛"}], "evidence": "想玩得松弛点"},
            ),
            _state(),
        )
    )
    assert result.ok
    assert result.data["proposed"] == ["PACE=松弛"]
    assert store.rows[("user-1", "PACE", "松弛")] == "PENDING"


def test_confirmation_requires_the_value_in_evidence() -> None:
    store = FakeProfileStore()
    _run_async_propose(store)
    result, _ = run_async(
        _tools(store).invoke(
            ToolCall(
                "update_preferences",
                {"confirmations": [{"category": "PACE", "value": "松弛"}], "evidence": "随便玩玩"},
            ),
            _state(),
        )
    )
    assert result.ok
    assert result.data["refused"] == ["PACE=松弛"]
    assert store.rows[("user-1", "PACE", "松弛")] == "PENDING"


def _run_async_propose(store: FakeProfileStore) -> None:
    run_async(
        _tools(store).invoke(
            ToolCall(
                "update_preferences",
                {"proposals": [{"category": "PACE", "value": "松弛"}], "evidence": "想玩得松弛点"},
            ),
            _state(),
        )
    )


def test_confirmation_with_evidence_confirms() -> None:
    store = FakeProfileStore()
    _run_async_propose(store)
    result, _ = run_async(
        _tools(store).invoke(
            ToolCall(
                "update_preferences",
                {
                    "confirmations": [{"category": "PACE", "value": "松弛"}],
                    "evidence": "以后都按松弛的来",
                },
            ),
            _state(),
        )
    )
    assert result.data["confirmed"] == ["PACE=松弛"]
    assert store.rows[("user-1", "PACE", "松弛")] == "CONFIRMED"


def test_revocation_is_immediate_and_blocks_revival() -> None:
    store = FakeProfileStore()
    _run_async_propose(store)
    result, _ = run_async(
        _tools(store).invoke(
            ToolCall(
                "update_preferences",
                {"revocations": [{"category": "PACE", "value": "松弛"}], "evidence": ""},
            ),
            _state(),
        )
    )
    assert result.data["revoked"] == ["PACE=松弛"]

    revival, _ = run_async(
        _tools(store).invoke(
            ToolCall(
                "update_preferences",
                {
                    "confirmations": [{"category": "PACE", "value": "松弛"}],
                    "evidence": "还是要松弛的",
                },
            ),
            _state(),
        )
    )
    assert revival.data["refused"] == ["PACE=松弛"]
    assert store.rows[("user-1", "PACE", "松弛")] == "REVOKED"


def test_unknown_categories_are_ignored() -> None:
    store = FakeProfileStore()
    result, _ = run_async(
        _tools(store).invoke(
            ToolCall(
                "update_preferences",
                {"proposals": [{"category": "MOOD", "value": "开心"}], "evidence": ""},
            ),
            _state(),
        )
    )
    assert result.ok
    assert result.data["invalid"] == ["MOOD=开心"]


def test_without_user_identity_the_tool_fails_closed() -> None:
    store = FakeProfileStore()
    result, _ = run_async(
        _tools(store).invoke(
            ToolCall(
                "update_preferences",
                {"proposals": [{"category": "PACE", "value": "RELAXED"}], "evidence": ""},
            ),
            _state(user_id=None),
        )
    )
    assert not result.ok
    assert result.error_code == "PROFILE_UNAVAILABLE"


def test_without_a_store_the_tool_fails_closed() -> None:
    result, _ = run_async(
        ToolRegistry.with_runtime(ToolRuntime()).invoke(
            ToolCall(
                "update_preferences",
                {"proposals": [{"category": "PACE", "value": "RELAXED"}], "evidence": ""},
            ),
            _state(),
        )
    )
    assert not result.ok
    assert result.error_code == "CAPABILITY_MISSING"


# ── SQL integration (gated on a real PostgreSQL) ────────────────────


def database_url() -> str:
    value = os.environ.get("KNOWLEDGE_TEST_DATABASE_URL", "").strip()
    if not value:
        pytest.skip("KNOWLEDGE_TEST_DATABASE_URL is not configured")
    return value


@pytest.fixture()
def profile_tables() -> TravelProfileRepository:
    repository = TravelProfileRepository(database_url())
    asyncio.run(repository.migrate())
    with psycopg.connect(database_url()) as connection:
        connection.execute("TRUNCATE agent.user_travel_profile")
    yield repository


def test_profile_repository_lifecycle(profile_tables: TravelProfileRepository) -> None:
    repository = profile_tables
    user_id = "00000000-0000-0000-0000-000000000001"
    proposed = asyncio.run(repository.propose(user_id=user_id, category="PACE", value="RELAXED"))
    assert proposed.status == "PENDING"

    confirmed = asyncio.run(repository.confirm(user_id=user_id, category="PACE", value="RELAXED"))
    assert confirmed is not None and confirmed.status == "CONFIRMED"

    # A re-proposal of a confirmed preference must not reset it.
    again = asyncio.run(repository.propose(user_id=user_id, category="PACE", value="RELAXED"))
    assert again.status == "CONFIRMED"

    revoked = asyncio.run(repository.revoke(user_id=user_id, category="PACE", value="RELAXED"))
    assert revoked is not None and revoked.status == "REVOKED"

    # A revoked preference refuses confirmation and never revives.
    refused_confirm = asyncio.run(
        repository.confirm(user_id=user_id, category="PACE", value="RELAXED")
    )
    assert refused_confirm is None
    revived = asyncio.run(repository.propose(user_id=user_id, category="PACE", value="RELAXED"))
    assert revived.status == "REVOKED"
    assert asyncio.run(repository.list_confirmed(user_id)) == ()
