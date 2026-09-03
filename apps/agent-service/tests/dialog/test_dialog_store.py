"""PsycopgDialogStore — delegates to the persistent agent-checkpoint repo.

Verified with a hand-rolled fake (the agent-service convention: no mock
framework).  The fake records that a run row is ensured before every save so
the checkpoint's FK is satisfied, and round-trips an AgentState snapshot.
"""

from __future__ import annotations

import asyncio

from trip_agent.agent.state import (
    AgentState,
    ConstraintSlots,
    SlotState,
    agent_state_from_dict,
    agent_state_to_dict,
)
from trip_agent.dialog.store import PsycopgDialogStore


class FakeRunRepository:
    """Records the repo contract the store depends on."""

    def __init__(self) -> None:
        self.checkpoints: dict[str, AgentState] = {}
        self.ensured: list[str] = []

    async def ensure_run(self, *, run_id: str, status: str = "RUNNING") -> None:
        self.ensured.append(run_id)

    async def save_checkpoint(self, *, run_id: str, state: AgentState) -> None:
        self.checkpoints[run_id] = state

    async def load_checkpoint(self, run_id: str) -> AgentState | None:
        return self.checkpoints.get(run_id)


def _sample_state() -> AgentState:
    slots = ConstraintSlots.empty()
    slots = slots.fill("destination", "广州", state=SlotState.CONFIRMED, verified_by="trip")
    return AgentState(slots=slots)


def test_save_ensures_run_then_persists_checkpoint() -> None:
    fake = FakeRunRepository()
    store = PsycopgDialogStore(fake)
    scope = "create:sess-1"
    state = _sample_state()

    asyncio.run(store.save(scope, agent_state_to_dict(state)))

    assert fake.ensured == ["create:sess-1"]
    assert "create:sess-1" in fake.checkpoints
    assert fake.checkpoints["create:sess-1"].slots.confirmed_values() == {"destination": "广州"}


def test_load_round_trips_agent_state() -> None:
    fake = FakeRunRepository()
    store = PsycopgDialogStore(fake)
    asyncio.run(store.save("create:sess-1", agent_state_to_dict(_sample_state())))
    fake.ensured.clear()

    raw = asyncio.run(store.load("create:sess-1"))

    assert raw is not None
    restored = agent_state_from_dict(raw)
    assert restored.slots.confirmed_values() == {"destination": "广州"}


def test_load_missing_scope_returns_none() -> None:
    store = PsycopgDialogStore(FakeRunRepository())

    assert asyncio.run(store.load("create:unknown")) is None