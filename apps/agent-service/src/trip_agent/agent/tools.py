"""Declarative tool layer — the agent's only window onto the world.

Hard facts (opening hours, route durations, coordinates) may only come from a
tool.  A tool that cannot establish a fact returns ``ok=False`` with an
explicit error code rather than a guessed value; the agent must surface the
gap instead of filling it in.

Every tool handler receives the current state and returns both a result and a
state update, so tools stay pure with respect to the agent loop.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from trip_agent.agent.itinerary_builder import BuiltItinerary
from trip_agent.agent.profile import PROFILE_CATEGORIES
from trip_agent.agent.state import AgentState, SlotState, goal_from_slots
from trip_agent.domain.planning.protocols import (
    PlanningInfeasibleError,
    PlanningProviderError,
)

logger = logging.getLogger(__name__)

type ToolHandler = Callable[
    [ToolCall, AgentState],
    Awaitable[tuple[ToolResult, dict[str, Any]]],
]


@dataclass(frozen=True, slots=True)
class ToolResult:
    """Outcome of one tool invocation."""

    ok: bool
    summary: str
    data: Any = None
    error_code: str | None = None

    @classmethod
    def failure(cls, error_code: str, summary: str) -> ToolResult:
        return cls(ok=False, summary=summary, error_code=error_code)


@dataclass(frozen=True, slots=True)
class ToolCall:
    """A requested tool invocation."""

    tool: str
    args: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """A tool's declaration surface.

    ``parameters`` is a JSON Schema object so the same declaration can be
    handed to a model for tool selection and to a validator for checking.
    """

    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler

    def declaration(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


@dataclass(frozen=True, slots=True)
class ToolRuntime:
    """External capabilities the tools delegate to.

    Every field is optional on purpose: a missing capability makes the
    corresponding tool fail closed instead of inventing a value.  This keeps
    the agent runnable with no provider keys configured.
    """

    feasibility: Callable[..., Awaitable[Any]] | None = None
    itinerary_builder: Callable[..., Awaitable[Any]] | None = None
    profile_store: Any | None = None


def _prop(description: str, kind: str = "string") -> dict[str, Any]:
    return {"type": kind, "description": description}


def _leaf_strings(value: Any) -> list[str]:
    """Flatten a structured slot value into the scalar texts it is made of."""
    if isinstance(value, dict):
        leaves: list[str] = []
        for item in value.values():
            leaves.extend(_leaf_strings(item))
        return leaves
    if isinstance(value, list | tuple | set | frozenset):
        leaves = []
        for item in value:
            leaves.extend(_leaf_strings(item))
        return leaves
    if value is None:
        return []
    text = str(value).strip()
    return [text] if text else []


def _evidence_confirms(value: Any, evidence: str) -> bool:
    """The rule that decides ``CONFIRMED``.

    The LLM may only propose.  A value becomes confirmed when the user's own
    words (the quoted evidence) actually contain it — never because the model
    says so.  Structured values (lists, dicts) confirm only when every scalar
    leaf appears in the evidence.
    """
    if not evidence:
        return False
    if isinstance(value, dict):
        leaves = _leaf_strings(value)
        return bool(leaves) and all(leaf in evidence for leaf in leaves)
    if isinstance(value, list | tuple | set | frozenset):
        items = [item for item in value if item is not None]
        return bool(items) and all(_evidence_confirms(item, evidence) for item in items)
    text = str(value).strip()
    return bool(text) and text in evidence


def _values_equal(left: Any, right: Any) -> bool:
    return bool(left == right or str(left) == str(right))


async def _update_constraints(
    call: ToolCall,
    state: AgentState,
) -> tuple[ToolResult, dict[str, Any]]:
    """Apply the LLM's slot proposals under code-side provenance rules.

    The model proposes; the code decides.  A value is CONFIRMED only when the
    quoted user evidence contains it (rule ``rule:evidence-match``); a change
    to an already-decided value becomes USER_OVERRIDE with the old value kept
    in ``override_of``.  A rejection records the value the model says was
    negated (the slot's current value when absent), so a proposal equal to a
    REJECTED value is refused.  The legacy ``confirmed`` flag is deliberately
    ignored — the LLM never self-certifies.
    """
    values = call.args.get("values") or {}
    if not isinstance(values, dict):
        return ToolResult.failure("INVALID_VALUES", "values must be an object"), {}
    evidence = str(call.args.get("evidence", ""))
    rejections = call.args.get("rejections") or {}
    if not isinstance(rejections, dict):
        return ToolResult.failure("INVALID_REJECTIONS", "rejections must be an object"), {}

    slots = state.slots
    applied: list[str] = []
    confirmed_names: list[str] = []
    inferred_names: list[str] = []
    rejected_names: list[str] = []
    refused: list[str] = []
    unknown: list[str] = []

    for name, value in rejections.items():
        try:
            slots.get(name)
        except KeyError:
            unknown.append(name)
            continue
        slots = slots.reject(name, value=value, evidence=evidence)
        rejected_names.append(name)

    for name, value in values.items():
        if value is None:
            continue
        try:
            slot = slots.get(name)
        except KeyError:
            unknown.append(name)
            continue
        if slot.is_rejected and _values_equal(slot.value, value):
            refused.append(name)
            continue
        if _evidence_confirms(value, evidence):
            if slot.state in (SlotState.CONFIRMED, SlotState.USER_OVERRIDE) and not _values_equal(
                slot.value, value
            ):
                slots = slots.override(
                    name, value, evidence=evidence, verified_by="rule:evidence-match"
                )
            else:
                slots = slots.fill(
                    name,
                    value,
                    state=SlotState.CONFIRMED,
                    evidence=evidence,
                    verified_by="rule:evidence-match",
                )
            confirmed_names.append(name)
        else:
            slots = slots.fill(name, value, state=SlotState.INFERRED, evidence=evidence)
            inferred_names.append(name)
        applied.append(name)

    summary_parts = []
    if applied:
        summary_parts.append(f"applied {', '.join(applied)}")
    if confirmed_names:
        summary_parts.append(f"rule-confirmed {', '.join(confirmed_names)}")
    if inferred_names:
        summary_parts.append(f"kept inferred {', '.join(inferred_names)}")
    if rejected_names:
        summary_parts.append(f"recorded rejections {', '.join(rejected_names)}")
    if refused:
        summary_parts.append(f"refused re-proposals of rejected values {', '.join(refused)}")
    if unknown:
        summary_parts.append(f"ignored unknown slots {', '.join(unknown)}")
    if not summary_parts:
        return ToolResult.failure("NO_VALUES", "no usable constraint values supplied"), {}
    partial: dict[str, Any] = {"slots": slots}
    if applied or rejected_names:
        # V3 D-3: a confirmed constraint change invalidates the stale
        # candidate and the failure context it was built under — the next
        # decision must rebuild, not re-ask the old question.  (The failure
        # memory is a single slot by design; the constraint change is what
        # resolves the failure it recorded.)  E-1: the reflection budget is
        # per constraint context, so a real change resets it too — and the
        # stored evaluation is the evaluation OF the invalidated candidate,
        # so it dies with it (otherwise the next observation classifier
        # would re-read the stale NEEDS_REPAIR and re-arm the failure memory
        # the change just cleared).
        partial["candidate_itinerary"] = None
        partial["plan_evaluation"] = None
        partial["failure_kind"] = None
        partial["failure_signature"] = None
        partial["failure_attempts"] = 0
        partial["reflection_attempts"] = 0
    return (
        ToolResult(
            ok=True,
            summary="; ".join(summary_parts),
            data={
                "applied": applied,
                "confirmed": confirmed_names,
                "inferred": inferred_names,
                "rejected": rejected_names,
                "refused": refused,
                "unknown": unknown,
            },
        ),
        partial,
    )


ALLOWED_EXPECTED_TYPES: frozenset[str] = frozenset({"text", "number", "date", "choice"})
MAX_ASK_OPTIONS = 10


async def _ask_user(call: ToolCall, _state: AgentState) -> tuple[ToolResult, dict[str, Any]]:
    """Request clarification and stop the loop for a human answer.

    ``options`` carries up to ten candidate answers and ``expected_type`` the
    kind of answer expected — both optional, both validated fail-closed.
    """
    question = str(call.args.get("question", "")).strip()
    if not question:
        return ToolResult.failure("EMPTY_QUESTION", "ask_user needs a question"), {}

    options = call.args.get("options")
    if options is not None:
        if (
            not isinstance(options, list)
            or len(options) > MAX_ASK_OPTIONS
            or not all(isinstance(item, str) and item.strip() for item in options)
        ):
            return (
                ToolResult.failure(
                    "INVALID_OPTIONS",
                    f"options must be a list of at most {MAX_ASK_OPTIONS} non-empty strings",
                ),
                {},
            )
        options = tuple(item.strip() for item in options)

    expected_type = call.args.get("expected_type")
    if expected_type is not None and expected_type not in ALLOWED_EXPECTED_TYPES:
        return (
            ToolResult.failure(
                "INVALID_EXPECTED_TYPE",
                "expected_type must be one of: " + ", ".join(sorted(ALLOWED_EXPECTED_TYPES)),
            ),
            {},
        )

    return (
        ToolResult(
            ok=True,
            summary=question,
            data={
                "question": question,
                "options": list(options) if options else None,
                "expected_type": expected_type,
            },
        ),
        {
            "pending_question": question,
            "pending_options": options,
            "pending_expected_type": expected_type,
            "stop_reason": "WAITING_USER",
        },
    )


async def _update_preferences(
    call: ToolCall,
    state: AgentState,
    runtime: ToolRuntime,
) -> tuple[ToolResult, dict[str, Any]]:
    """Propose, confirm, or revoke cross-session preferences (P3.2).

    Confirmation follows the same trust rule as constraint slots: the value
    must appear in the user's verbatim evidence.  Revocation is immediate,
    and a revoked preference never revives by re-proposal.
    """
    if runtime.profile_store is None:
        return (
            ToolResult.failure("CAPABILITY_MISSING", "profile store is not configured"),
            {},
        )
    if not state.user_id:
        return (
            ToolResult.failure("PROFILE_UNAVAILABLE", "no user identity on this run"),
            {},
        )
    evidence = str(call.args.get("evidence", ""))
    proposals = call.args.get("proposals") or []
    confirmations = call.args.get("confirmations") or []
    revocations = call.args.get("revocations") or []
    if not all(isinstance(group, list) for group in (proposals, confirmations, revocations)):
        return (
            ToolResult.failure(
                "INVALID_PREFERENCES", "proposals/confirmations/revocations must be lists"
            ),
            {},
        )

    proposed: list[str] = []
    confirmed: list[str] = []
    refused: list[str] = []
    revoked: list[str] = []
    invalid: list[str] = []

    async def _apply(group: list[Any], action: str) -> None:
        nonlocal proposed, confirmed, refused, revoked, invalid
        for item in group:
            if not isinstance(item, dict):
                invalid.append("?")
                continue
            category = str(item.get("category", "")).strip().upper()
            value = str(item.get("value", "")).strip()
            label = f"{category}={value}"
            if category not in PROFILE_CATEGORIES or not value or len(value) > 120:
                invalid.append(label)
                continue
            store = runtime.profile_store
            if action == "propose":
                record = await store.propose(user_id=state.user_id, category=category, value=value)
                proposed.append(label)
            elif action == "confirm":
                if not _evidence_confirms(value, evidence):
                    refused.append(label)
                    continue
                record = await store.confirm(user_id=state.user_id, category=category, value=value)
                if record is None:
                    refused.append(label)
                else:
                    confirmed.append(label)
            else:
                record = await store.revoke(user_id=state.user_id, category=category, value=value)
                if record is None:
                    refused.append(label)
                else:
                    revoked.append(label)

    await _apply(proposals, "propose")
    await _apply(confirmations, "confirm")
    await _apply(revocations, "revoke")

    summary_parts = []
    if proposed:
        summary_parts.append(f"proposed {', '.join(proposed)}")
    if confirmed:
        summary_parts.append(f"confirmed {', '.join(confirmed)}")
    if revoked:
        summary_parts.append(f"revoked {', '.join(revoked)}")
    if refused:
        summary_parts.append(f"refused (no evidence or revoked) {', '.join(refused)}")
    if invalid:
        summary_parts.append(f"ignored invalid {', '.join(invalid)}")
    if not summary_parts:
        return ToolResult.failure("NO_PREFERENCES", "no usable preference entries"), {}
    return (
        ToolResult(
            ok=True,
            summary="; ".join(summary_parts),
            data={
                "proposed": proposed,
                "confirmed": confirmed,
                "revoked": revoked,
                "refused": refused,
                "invalid": invalid,
            },
        ),
        {},
    )


async def _build_itinerary(
    _call: ToolCall,
    state: AgentState,
    runtime: ToolRuntime,
) -> tuple[ToolResult, dict[str, Any]]:
    """Draft an itinerary by triggering the deterministic planning pipeline.

    The pipeline owns scheduling truth; this tool forwards the confirmed
    constraints and records the returned draft as the validation candidate.
    The pipeline is never invoked on incomplete or unconfirmed constraints.
    """
    if runtime.itinerary_builder is None:
        return (
            ToolResult.failure("CAPABILITY_MISSING", "itinerary building is not configured"),
            {},
        )
    missing = state.slots.missing_required()
    if missing:
        return (
            ToolResult.failure(
                "INCOMPLETE_CONSTRAINTS", f"required slots missing: {', '.join(missing)}"
            ),
            {},
        )
    try:
        built = await runtime.itinerary_builder(
            slots=state.slots, trip_id=state.trip_id
        )
    except PlanningInfeasibleError as error:
        detail = (
            "; ".join(conflict.message for conflict in error.conflicts)
            or "planning is infeasible under the confirmed constraints"
        )
        # V3 C-1: report the deterministic conflict; what to do about it
        # (ask the user / stop / rebuild) is the DECIDER's policy, not the
        # tool's — the trajectory benchmark's ask-the-user policy relies on
        # this separation.  V3 D-1: the structured conflict codes travel in
        # data so the failure classifier can sub-categorize without
        # string-matching the message.
        return (
            ToolResult(
                ok=False,
                summary=detail,
                data={"conflict_codes": [
                    conflict.code for conflict in error.conflicts
                ]},
                error_code="PLANNING_INFEASIBLE",
            ),
            {},
        )
    except PlanningProviderError as error:
        # V3 D-1: preserve the structured provider error (category /
        # error_code) through the boundary — collapsing it into TOOL_ERROR
        # would erase exactly the information the failure classifier needs
        # to tell a transient timeout from a deterministic refusal.
        details = error.details
        return (
            ToolResult(
                ok=False,
                summary=details.safe_message or str(error),
                data=None,
                error_code=details.error_code or details.category.value,
            ),
            {},
        )
    except ValueError as error:
        return ToolResult.failure("INVALID_CONSTRAINT_VALUES", str(error)), {}
    if isinstance(built, BuiltItinerary):
        # V3 C-1: real backend — the observation carries the provider and the
        # hard-validation summary; the structural gate stays the EMITTED judge.
        wire = built.itinerary.model_dump(mode="json", by_alias=True, exclude_none=True)
        feasibility_note = ""
        if built.feasibility is not None:
            failures = built.feasibility.get("failures") or []
            feasibility_note = (
                f"; hard validation {built.feasibility.get('status')}"
                + (f" ({len(failures)} failing rules)" if failures else "")
            )
            # E-1 Case C: quality feedback surfaces with the observation —
            # recorded, shown, injected into the decision context; it never
            # blocks emission and never becomes a failure.
            quality = built.feasibility.get("quality")
            if isinstance(quality, dict) and quality.get("verdict"):
                feasibility_note += (
                    f"; quality {quality.get('score')} ({quality.get('verdict')})"
                )
        return (
            ToolResult(
                ok=True,
                summary=(
                    f"itinerary drafted via {built.provider_name}: "
                    f"{built.itinerary.title} ({len(built.itinerary.days)} days)"
                    + feasibility_note
                ),
                data=wire,
            ),
            {
                "candidate_itinerary": wire,
                # V3 C-3: the run goal and the real plan's decision/evaluation
                # memory enter the Agent State (checkpoint v2).
                "goal": state.goal or goal_from_slots(state.slots),
                "plan_evaluation": built.feasibility,
                "decision_summaries": built.decision_summaries,
            },
        )
    wire = built.model_dump(mode="json", by_alias=True, exclude_none=True)
    return (
        ToolResult(
            ok=True,
            summary=f"itinerary drafted: {built.title} ({len(built.days)} days)",
            data=wire,
        ),
        {"candidate_itinerary": wire},
    )


async def _validate_itinerary(
    _call: ToolCall,
    state: AgentState,
    runtime: ToolRuntime,
) -> tuple[ToolResult, dict[str, Any]]:
    """Run the deterministic feasibility gate over the candidate itinerary.

    The veto lands on the real itinerary object — a passing gate auto-emits
    the candidate (the loop emits; the model has no emit tool).
    """
    if runtime.feasibility is None:
        return (
            ToolResult.failure("CAPABILITY_MISSING", "feasibility gate is not configured"),
            {},
        )
    if state.candidate_itinerary is None:
        return (
            ToolResult.failure(
                "NO_CANDIDATE", "build_itinerary must produce a candidate first"
            ),
            {},
        )
    report = await runtime.feasibility(
        itinerary=state.candidate_itinerary, slots=state.slots.confirmed_values()
    )
    blocker = bool(getattr(report, "has_blocker", False))
    return (
        ToolResult(
            ok=not blocker,
            summary="feasibility gate: blocked" if blocker else "feasibility gate: passed",
            data=report,
            error_code=None if not blocker else "FEASIBILITY_BLOCKED",
        ),
        {},
    )


def build_tool_specs(runtime: ToolRuntime) -> tuple[ToolSpec, ...]:
    """Declare the tool surface bound to ``runtime``."""
    return (
        ToolSpec(
            name="update_constraints",
            description=(
                "Propose trip constraints extracted from the user. Provenance is "
                "decided by code: a value is confirmed only when the quoted user "
                "evidence contains it."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "values": {
                        "type": "object",
                        "description": "Slot name to value, e.g. destination, budget.",
                    },
                    "evidence": _prop("Verbatim quote of the user's words supporting the values."),
                    "rejections": {
                        "type": "object",
                        "description": (
                            "Slot names the user explicitly rejected, mapped to the "
                            "rejected value."
                        ),
                    },
                },
                "required": ["values"],
            },
            handler=_update_constraints,
        ),
        ToolSpec(
            name="ask_user",
            description="Ask the user a clarifying question and wait for the answer.",
            parameters={
                "type": "object",
                "properties": {
                    "question": _prop("The question to ask."),
                    "options": {
                        "type": "array",
                        "items": {"type": "string"},
                        "maxItems": MAX_ASK_OPTIONS,
                        "description": "Up to ten candidate answers shown as choices.",
                    },
                    "expected_type": {
                        "type": "string",
                        "enum": sorted(ALLOWED_EXPECTED_TYPES),
                        "description": "The kind of answer expected.",
                    },
                },
                "required": ["question"],
            },
            handler=_ask_user,
        ),
        ToolSpec(
            name="update_preferences",
            description=(
                "Propose, confirm, or revoke cross-session travel preferences. "
                "Confirmation requires the value in the user's evidence; "
                "revoked preferences never revive."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "proposals": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "category": {"type": "string"},
                                "value": {"type": "string"},
                            },
                        },
                        "description": "New preferences to record as pending.",
                    },
                    "confirmations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "category": {"type": "string"},
                                "value": {"type": "string"},
                            },
                        },
                        "description": "Preferences the user confirmed in this turn's evidence.",
                    },
                    "revocations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "category": {"type": "string"},
                                "value": {"type": "string"},
                            },
                        },
                        "description": "Preferences the user explicitly withdrew.",
                    },
                    "evidence": _prop("Verbatim quote of the user's words."),
                },
            },
            handler=lambda call, state: _update_preferences(call, state, runtime),
        ),
        ToolSpec(
            name="build_itinerary",
            description=(
                "Trigger the deterministic planning pipeline on the confirmed "
                "constraints and record the draft as the validation candidate."
            ),
            parameters={"type": "object", "properties": {}},
            handler=lambda call, state: _build_itinerary(call, state, runtime),
        ),
        ToolSpec(
            name="validate_itinerary",
            description=(
                "Run the deterministic feasibility gate over the drafted "
                "itinerary. A passing gate auto-emits it."
            ),
            parameters={"type": "object", "properties": {}},
            handler=lambda call, state: _validate_itinerary(call, state, runtime),
        ),
    )


class ToolRegistry:
    """Name → spec lookup with fail-closed invocation."""

    def __init__(self, specs: tuple[ToolSpec, ...] = ()) -> None:
        self._specs = {spec.name: spec for spec in specs}

    @classmethod
    def with_runtime(cls, runtime: ToolRuntime) -> ToolRegistry:
        return cls(build_tool_specs(runtime))

    def names(self) -> tuple[str, ...]:
        return tuple(self._specs)

    def declarations(self) -> tuple[dict[str, Any], ...]:
        return tuple(spec.declaration() for spec in self._specs.values())

    def has(self, name: str) -> bool:
        return name in self._specs

    async def invoke(self, call: ToolCall, state: AgentState) -> tuple[ToolResult, dict[str, Any]]:
        """Invoke a tool, returning (result, state update).

        Unknown tools and handler exceptions are reported as failures rather
        than raising, so a bad model output or a broken provider cannot take
        the run down.
        """
        spec = self._specs.get(call.tool)
        if spec is None:
            return (
                ToolResult.failure("UNKNOWN_TOOL", f"no such tool: {call.tool}"),
                {},
            )
        try:
            return await spec.handler(call, state)
        except Exception as exc:
            logger.warning("agent_tool_handler_error tool=%s error=%s", call.tool, exc)
            return (
                ToolResult.failure("TOOL_ERROR", f"tool '{call.tool}' failed: {exc}"),
                {},
            )
