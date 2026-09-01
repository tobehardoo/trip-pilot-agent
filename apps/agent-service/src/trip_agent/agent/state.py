"""Agent working memory — constraint slots and tool observations.

A constraint slot carries its provenance, not just its value.  Only a
``CONFIRMED`` slot may become a hard constraint; an ``INFERRED`` slot is at
most a soft preference.  This is the fail-closed rule applied to memory: the
agent must ask rather than quietly assume.

Slot names mirror ``TripConstraints`` so a filled slot set can be projected
onto the existing planning contract without translation.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class SlotState(str, Enum):
    """How a slot value was obtained.

    ``REJECTED`` records that the user explicitly negated a candidate value —
    the value is kept for memory, but the slot is not satisfied and the same
    value must not be proposed again.  ``USER_OVERRIDE`` records a user-set
    replacement of a previously decided value; it is as strong as
    ``CONFIRMED`` (the user stated it) but keeps an audit chain.
    """

    UNKNOWN = "UNKNOWN"
    INFERRED = "INFERRED"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    USER_OVERRIDE = "USER_OVERRIDE"


HARD_STATES: frozenset[SlotState] = frozenset(
    {SlotState.CONFIRMED, SlotState.USER_OVERRIDE}
)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass(frozen=True, slots=True)
class ConstraintSlot:
    """One constraint together with the provenance of its value.

    ``verified_by`` names the rule or actor that decided the state (e.g.
    ``"rule:evidence-match"``, ``"user"``).  ``override_of`` keeps the
    previous value when a user replaced one.  ``updated_at`` is refreshed on
    every write.
    """

    value: Any = None
    state: SlotState = SlotState.UNKNOWN
    evidence: str = ""
    verified_by: str = ""
    override_of: Any = None
    updated_at: str = ""

    @property
    def filled(self) -> bool:
        return self.value is not None

    @property
    def hard(self) -> bool:
        """True only when the value may act as a hard constraint.

        An inferred value is a hint for ranking, never a constraint the
        planner must satisfy.
        """
        return self.state in HARD_STATES and self.value is not None

    @property
    def is_rejected(self) -> bool:
        return self.state is SlotState.REJECTED


REQUIRED_SLOTS: tuple[str, ...] = ("destination", "start_date", "end_date")

OPTIONAL_SLOTS: tuple[str, ...] = (
    "budget",
    "travelers",
    "pace",
    "must_visit",
    "avoid",
    "fixed_schedules",
    "accommodation",
    "arrival",
    "departure",
    "mobility",
)

SLOT_NAMES: tuple[str, ...] = REQUIRED_SLOTS + OPTIONAL_SLOTS


@dataclass(frozen=True, slots=True)
class ConstraintSlots:
    """Immutable set of constraint slots."""

    slots: dict[str, ConstraintSlot] = field(default_factory=dict)

    @classmethod
    def empty(cls) -> ConstraintSlots:
        return cls(slots={name: ConstraintSlot() for name in SLOT_NAMES})

    def get(self, name: str) -> ConstraintSlot:
        try:
            return self.slots[name]
        except KeyError:
            raise KeyError(f"unknown constraint slot: {name}") from None

    def fill(
        self,
        name: str,
        value: Any,
        *,
        state: SlotState,
        evidence: str = "",
        verified_by: str = "",
        override_of: Any = None,
    ) -> ConstraintSlots:
        """Return a new slot set with ``name`` filled at the given provenance."""
        self.get(name)
        updated = dict(self.slots)
        updated[name] = ConstraintSlot(
            value=value,
            state=state,
            evidence=evidence,
            verified_by=verified_by,
            override_of=override_of,
            updated_at=_now(),
        )
        return replace(self, slots=updated)

    def confirm(self, name: str) -> ConstraintSlots:
        """Promote an already-filled slot to CONFIRMED, keeping its metadata."""
        slot = self.get(name)
        if not slot.filled:
            return self
        return self.fill(
            name,
            slot.value,
            state=SlotState.CONFIRMED,
            evidence=slot.evidence,
            verified_by=slot.verified_by,
            override_of=slot.override_of,
        )

    def reject(
        self,
        name: str,
        *,
        value: Any = None,
        evidence: str = "",
    ) -> ConstraintSlots:
        """Record the user's explicit rejection of a candidate value.

        ``value`` is the negated candidate — when omitted, the slot's current
        value is used.  The value is kept for memory so the same candidate is
        never proposed again.
        """
        slot = self.get(name)
        return self.fill(
            name,
            slot.value if value is None else value,
            state=SlotState.REJECTED,
            evidence=evidence or slot.evidence,
            verified_by="user",
        )

    def override(
        self,
        name: str,
        value: Any,
        *,
        evidence: str = "",
        verified_by: str = "user",
    ) -> ConstraintSlots:
        """Replace a decided value with a user-set one, keeping the audit chain."""
        slot = self.get(name)
        return self.fill(
            name,
            value,
            state=SlotState.USER_OVERRIDE,
            evidence=evidence,
            verified_by=verified_by,
            override_of=slot.value,
        )

    def rejected_values(self) -> dict[str, Any]:
        """Values the user explicitly rejected — never propose these again."""
        return {
            name: slot.value
            for name, slot in self.slots.items()
            if slot.state is SlotState.REJECTED
        }

    def missing_required(self) -> tuple[str, ...]:
        """Required slots that are not yet confirmed."""
        return tuple(name for name in REQUIRED_SLOTS if not self.get(name).hard)

    def confirmed_values(self) -> dict[str, Any]:
        """Confirmed values only — the projection onto hard constraints."""
        return {name: slot.value for name, slot in self.slots.items() if slot.hard}


# Slots that map onto TripConstraints fields.
TRIP_CONSTRAINT_FIELD: dict[str, str] = {
    "budget": "budget_amount",
    "travelers": "travelers",
    "pace": "pace",
    "must_visit": "must_visit_places",
    "avoid": "avoid_places",
    "fixed_schedules": "fixed_schedules",
    "accommodation": "accommodation",
    "arrival": "arrival",
    "departure": "departure",
    "mobility": "mobility_level",
}

# Slots that live on TripSnapshot rather than on TripConstraints.
TRIP_LEVEL_SLOTS: tuple[str, ...] = ("destination", "start_date", "end_date")


def to_constraint_patch(slots: ConstraintSlots) -> dict[str, Any]:
    """Project confirmed slots onto ``TripConstraints`` field names.

    Only confirmed values are projected — an inferred value must never reach
    the planner as a constraint.  Trip-level slots are exposed separately by
    :func:`to_trip_fields`.
    """
    values = slots.confirmed_values()
    return {
        field_name: values[slot_name]
        for slot_name, field_name in TRIP_CONSTRAINT_FIELD.items()
        if slot_name in values
    }


def to_trip_fields(slots: ConstraintSlots) -> dict[str, Any]:
    """Project confirmed trip-level slots (destination and dates)."""
    values = slots.confirmed_values()
    return {name: values[name] for name in TRIP_LEVEL_SLOTS if name in values}


@dataclass(frozen=True, slots=True)
class ToolObservation:
    """What a tool returned, recorded for the trajectory and for the model."""

    tool: str
    ok: bool
    summary: str
    data: Any = None
    error_code: str | None = None

    def render(self) -> str:
        status = "OK" if self.ok else f"FAILED({self.error_code})"
        return f"[{self.tool}] {status}: {self.summary}"


@dataclass(frozen=True)
class AgentState:
    """Working memory for a single agent run.

    This is the LangGraph state object.  Nodes return partial updates
    (plain dicts) rather than mutating the state in place.
    """

    slots: ConstraintSlots = field(default_factory=ConstraintSlots.empty)
    observations: tuple[ToolObservation, ...] = ()
    pending_question: str | None = None
    pending_options: tuple[str, ...] | None = None
    pending_expected_type: str | None = None
    pending_call: Any = None
    steps: int = 0
    stop_reason: str | None = None
    answer: str | None = None
    user_message: str | None = None
    # P2.2: the drafted itinerary (wire dict) awaiting the feasibility gate,
    # plus the run's trip identity for downstream builders/events.
    candidate_itinerary: dict[str, Any] | None = None
    trip_id: str | None = None
    # Ceilings are per-dialog-turn (P2.1): a resumed turn starts a fresh step
    # budget with the observation baseline frozen at the turn's start.
    turn_baseline_observations: int = 0
    # P3.2: run identity for the cross-session profile, plus the confirmed
    # preferences injected into decisions (never unconfirmed ones).
    user_id: str | None = None
    confirmed_preferences: tuple[tuple[str, str], ...] = ()
    # P3.3: the explicitly declared strategy of the latest decision.
    strategy: str | None = None
    # V3 C-3: the structured run goal (derived from confirmed slots) and the
    # real plan's evaluation/decision memory — the Phase B decision assets
    # finally live in the Agent State instead of provider locals.
    goal: str = ""
    plan_evaluation: dict[str, Any] | None = None
    decision_summaries: tuple[str, ...] = ()
    # V3 D-1: failure memory — the classified kind, a deterministic
    # signature for repetition detection, and the count of CONSECUTIVE
    # identical failures.  Written by the loop after every observation;
    # read by the decider from D-2/D-3/D-4 onward (D-1 only records).
    failure_kind: str | None = None
    failure_signature: str | None = None
    failure_attempts: int = 0
    # E-1: reflection budget — how many evaluation-rejected candidates the
    # loop has produced under the CURRENT constraint context.  Incremented
    # on a REJECT_HARD build observation, reset together with the failure
    # memory when the user applies a constraint change.  Bounded so a
    # misbehaving decider can never REPLAN without end (Case D).
    reflection_attempts: int = 0

    def with_observation(self, observation: ToolObservation) -> dict[str, Any]:
        """Partial update appending one observation."""
        return {"observations": (*self.observations, observation)}

    def recent_observations(self, limit: int = 8) -> str:
        if not self.observations:
            return "(no tool calls yet)"
        return "\n".join(item.render() for item in self.observations[-limit:])


def goal_from_slots(slots: ConstraintSlots) -> str:
    """Derive the run goal from the confirmed constraint slots."""
    values = slots.confirmed_values()
    destination = str(values.get("destination") or "").strip() or "目的地待定"
    start = values.get("start_date")
    end = values.get("end_date")
    window = f"{start} 至 {end}" if start and end else "日期待定"
    travelers = values.get("travelers")
    party = f"，{travelers} 人" if travelers else ""
    return f"规划 {destination} {window} 的旅行行程{party}"


CHECKPOINT_VERSION = 2
# v1 checkpoints (pre-C-3) stay readable: the new fields default to empty.
_READABLE_VERSIONS = (1, 2)


def _json_safe(value: Any) -> Any:
    """Degrade a non-JSON payload to its textual form instead of failing.

    Checkpoints favour availability over fidelity: a rich provider object is
    kept as a string, and full-fidelity trajectory detail lives in the
    append-only step records.
    """
    try:
        json.dumps(value)
    except TypeError:
        return str(value)
    return value


def _pending_call_to_dict(call: Any) -> dict[str, Any] | None:
    if call is None:
        return None
    tool = getattr(call, "tool", None)
    args = getattr(call, "args", None)
    return {"tool": str(tool), "args": _json_safe(args or {})}


def agent_state_to_dict(state: AgentState) -> dict[str, Any]:
    """Serialize the working memory for a checkpoint.

    The layout is versioned; :func:`agent_state_from_dict` refuses unknown
    versions rather than guessing.
    """
    return {
        "version": CHECKPOINT_VERSION,
        "slots": {
            name: {
                "value": _json_safe(slot.value),
                "state": slot.state.value,
                "evidence": slot.evidence,
                "verified_by": slot.verified_by,
                "override_of": _json_safe(slot.override_of),
                "updated_at": slot.updated_at,
            }
            for name, slot in state.slots.slots.items()
        },
        "observations": [
            {
                "tool": obs.tool,
                "ok": obs.ok,
                "summary": obs.summary,
                "data": _json_safe(obs.data),
                "error_code": obs.error_code,
            }
            for obs in state.observations
        ],
        "pending_question": state.pending_question,
        "pending_options": (
            list(state.pending_options) if state.pending_options is not None else None
        ),
        "pending_expected_type": state.pending_expected_type,
        "pending_call": _pending_call_to_dict(state.pending_call),
        "steps": state.steps,
        "stop_reason": state.stop_reason,
        "answer": state.answer,
        "user_message": state.user_message,
        "candidate_itinerary": state.candidate_itinerary,
        "trip_id": state.trip_id,
        "turn_baseline_observations": state.turn_baseline_observations,
        "user_id": state.user_id,
        "confirmed_preferences": [
            [category, value] for category, value in state.confirmed_preferences
        ],
        "strategy": state.strategy,
        "goal": state.goal,
        "plan_evaluation": _json_safe(state.plan_evaluation),
        "decision_summaries": list(state.decision_summaries),
        "failure_kind": state.failure_kind,
        "failure_signature": state.failure_signature,
        "failure_attempts": state.failure_attempts,
        "reflection_attempts": state.reflection_attempts,
    }


def agent_state_from_dict(data: Mapping[str, Any]) -> AgentState:
    """Restore working memory from a checkpoint; unknown versions fail closed."""
    if data.get("version") not in _READABLE_VERSIONS:
        raise ValueError(f"unsupported agent checkpoint version: {data.get('version')!r}")

    # Deferred import: tools.py imports this module at load time.
    from trip_agent.agent.tools import ToolCall

    slots = ConstraintSlots(
        slots={
            name: ConstraintSlot(
                value=slot.get("value"),
                state=SlotState(slot["state"]),
                evidence=slot.get("evidence", ""),
                verified_by=slot.get("verified_by", ""),
                override_of=slot.get("override_of"),
                updated_at=slot.get("updated_at", ""),
            )
            for name, slot in (data.get("slots") or {}).items()
        }
    )
    observations = tuple(
        ToolObservation(
            tool=obs["tool"],
            ok=bool(obs["ok"]),
            summary=obs["summary"],
            data=obs.get("data"),
            error_code=obs.get("error_code"),
        )
        for obs in data.get("observations") or []
    )
    pending_options = data.get("pending_options")
    pending_call = data.get("pending_call")
    return AgentState(
        slots=slots,
        observations=observations,
        pending_question=data.get("pending_question"),
        pending_options=(
            tuple(pending_options) if pending_options is not None else None
        ),
        pending_expected_type=data.get("pending_expected_type"),
        pending_call=ToolCall(**pending_call) if pending_call else None,
        steps=int(data.get("steps", 0)),
        stop_reason=data.get("stop_reason"),
        answer=data.get("answer"),
        user_message=data.get("user_message"),
        candidate_itinerary=data.get("candidate_itinerary"),
        trip_id=data.get("trip_id"),
        turn_baseline_observations=int(data.get("turn_baseline_observations", 0)),
        user_id=data.get("user_id"),
        confirmed_preferences=tuple(
            (category, value)
            for category, value in (data.get("confirmed_preferences") or ())
        ),
        strategy=data.get("strategy"),
        goal=data.get("goal", ""),
        plan_evaluation=data.get("plan_evaluation"),
        decision_summaries=tuple(data.get("decision_summaries") or ()),
        failure_kind=data.get("failure_kind"),
        failure_signature=data.get("failure_signature"),
        failure_attempts=int(data.get("failure_attempts", 0)),
        reflection_attempts=int(data.get("reflection_attempts", 0)),
    )
