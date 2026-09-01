"""V3 D-1 — deterministic failure classification.

One pure entry point (``classify_failure``) turns structured observation
evidence into a FailureKind + a stable signature; ``advance_failure_memory``
folds consecutive identical failures into an attempt count.  D-1 only
understands failures — no recovery action is chosen here (D-2/D-3/D-4).

Counterfactual discipline (user §十八): changing the NATURE of the failure
must change the kind — not merely the error string.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from trip_agent.agent import (
    AgentLoop,
    AgentState,
    AskingDecider,
    ConstraintSlots,
    SlotState,
    StructuralFeasibilityGate,
    ToolCall,
    ToolRegistry,
    ToolRuntime,
    run_agent,
)
from trip_agent.agent.failure_policy import (
    advance_failure_memory,
    classify_failure,
)
from trip_agent.domain.planning.protocols import (
    PlanningProviderError,
)
from trip_agent.providers.errors import TRANSIENT_CATEGORIES

# ── Test 1: Transient ────────────────────────────────────────────────────────


def test_every_transient_category_value_classifies_as_transient() -> None:
    """F-2b: _TRANSIENT_CODES derives from providers/errors TRANSIENT_CATEGORIES
    — every bare category value, including QUOTA_EXCEEDED, must classify
    TRANSIENT so the derivation can never silently drop one."""
    for category in TRANSIENT_CATEGORIES:
        kind, _ = classify_failure(tool="build_itinerary", ok=False, error_code=category.value)
        assert kind == "TRANSIENT", category.value


def test_provider_timeout_classifies_as_transient() -> None:
    for code in ("NETWORK_ERROR", "PROVIDER_UNAVAILABLE", "RATE_LIMITED", "TIMEOUT"):
        kind, signature = classify_failure(tool="build_itinerary", ok=False, error_code=code)
        assert kind == "TRANSIENT", code
        assert signature == f"TRANSIENT:build_itinerary:{code}"


def test_production_transient_codes_classify_as_transient() -> None:
    """V3 D-2: the agent boundary surfaces the provider's own ``error_code``
    (the prefixed ``ProviderErrorCode`` forms, providers/map.py:76-88), so a
    real timeout / rate limit / quota exhaustion arrives prefixed — these
    must classify TRANSIENT, not INTERNAL (Fact B, Phase-D2 design verdict)."""
    for code in (
        "PROVIDER_TIMEOUT",
        "PROVIDER_RATE_LIMITED",
        "PROVIDER_QUOTA_EXHAUSTED",
    ):
        kind, signature = classify_failure(tool="build_itinerary", ok=False, error_code=code)
        assert kind == "TRANSIENT", code
        assert signature == f"TRANSIENT:build_itinerary:{code}"


def test_provider_error_stays_internal() -> None:
    """``PROVIDER_ERROR`` is the deterministic adapter fallback
    (INVALID_REQUEST / PROVIDER_ADAPTER_ERROR, retryable=False) — it must
    never be retried as a transient blip."""
    kind, signature = classify_failure(
        tool="build_itinerary", ok=False, error_code="PROVIDER_ERROR"
    )
    assert kind == "INTERNAL"
    assert signature == "INTERNAL:build_itinerary:PROVIDER_ERROR"


# ── Test 2: Capability ───────────────────────────────────────────────────────


def test_capability_missing_classifies_as_capability() -> None:
    kind, signature = classify_failure(
        tool="search_place", ok=False, error_code="CAPABILITY_MISSING"
    )
    assert kind == "CAPABILITY_MISSING"
    assert signature == "CAPABILITY_MISSING:search_place"


# ── Test 3: User Constraint (validation reason) ─────────────────────────────


def test_must_visit_place_missing_classifies_as_user_constraint() -> None:
    kind, signature = classify_failure(
        tool="build_itinerary",
        ok=True,
        validation_reason_codes=("MUST_VISIT_PLACE_MISSING",),
    )
    assert kind == "USER_CONSTRAINT"
    assert signature == "USER_CONSTRAINT:build_itinerary:MUST_VISIT_PLACE_MISSING"


# ── Test 4: Candidate Empty ──────────────────────────────────────────────────


def test_insufficient_pois_classify_as_candidate_empty() -> None:
    for code in ("INSUFFICIENT_AMAP_POIS", "NO_RESULT"):
        kind, signature = classify_failure(tool="build_itinerary", ok=False, error_code=code)
        assert kind == "CANDIDATE_EMPTY", code
        assert signature == f"CANDIDATE_EMPTY:build_itinerary:{code}"


# ── Test 5: Feasibility (gate refusal) ───────────────────────────────────────


def test_feasibility_blocked_classifies_as_feasibility() -> None:
    kind, signature = classify_failure(
        tool="validate_itinerary", ok=False, error_code="FEASIBILITY_BLOCKED"
    )
    assert kind == "FEASIBILITY"
    assert signature == "FEASIBILITY:validate_itinerary"


# ── Test 6: Validation (hard rule failure) ───────────────────────────────────


def test_unrecognized_validation_reason_classifies_as_validation() -> None:
    """A hard-validation failure whose reason has no domain mapping falls
    back to VALIDATION; recognized reasons map to their domain kind
    (see test_route_continuity_maps_to_feasibility)."""
    kind, signature = classify_failure(
        tool="build_itinerary",
        ok=True,
        validation_reason_codes=("SOME_FUTURE_RULE",),
    )
    assert kind == "VALIDATION"
    assert "SOME_FUTURE_RULE" in signature


def test_route_continuity_maps_to_feasibility() -> None:
    kind, _ = classify_failure(
        tool="build_itinerary",
        ok=True,
        validation_reason_codes=("ROUTE_ENDPOINT_CONTINUITY",),
    )
    assert kind == "FEASIBILITY"


# ── Test 7: Unknown / Internal ───────────────────────────────────────────────


def test_unknown_and_tool_error_classify_as_internal() -> None:
    for code in (None, "TOOL_ERROR", "SOMETHING_NEW"):
        kind, signature = classify_failure(
            tool="build_itinerary", ok=False, error_code=code
        )
        assert kind == "INTERNAL", code
        assert signature.startswith("INTERNAL:build_itinerary")


# ── PlanningInfeasible sub-categorization (user §九) ─────────────────────────


def test_infeasible_structured_conflicts_split_user_constraint_vs_feasibility() -> None:
    user, user_sig = classify_failure(
        tool="build_itinerary",
        ok=False,
        error_code="PLANNING_INFEASIBLE",
        data={"conflict_codes": ["MUST_VISIT_UNAVAILABLE"]},
    )
    assert user == "USER_CONSTRAINT"
    assert user_sig == "USER_CONSTRAINT:build_itinerary:MUST_VISIT_UNAVAILABLE"

    geo, geo_sig = classify_failure(
        tool="build_itinerary",
        ok=False,
        error_code="PLANNING_INFEASIBLE",
        data={"conflict_codes": ["INSUFFICIENT_DAY_CAPACITY"]},
    )
    assert geo == "FEASIBILITY"
    assert geo_sig == "FEASIBILITY:build_itinerary:INSUFFICIENT_DAY_CAPACITY"


def test_infeasible_without_conflicts_falls_back_to_user_constraint() -> None:
    kind, signature = classify_failure(
        tool="build_itinerary", ok=False, error_code="PLANNING_INFEASIBLE", data=None
    )
    assert kind == "USER_CONSTRAINT"
    assert signature == "USER_CONSTRAINT:build_itinerary:PLANNING_INFEASIBLE"


def test_infeasible_mixed_conflicts_pick_deterministically() -> None:
    kind, _ = classify_failure(
        tool="build_itinerary",
        ok=False,
        error_code="PLANNING_INFEASIBLE",
        data={"conflict_codes": ["INSUFFICIENT_DAY_CAPACITY", "MUST_VISIT_UNAVAILABLE"]},
    )
    assert kind == "USER_CONSTRAINT"  # taxonomy order: user constraint first


# ── TOOL_ERROR boundary (user §八) ───────────────────────────────────────────


def test_opaque_tool_error_is_internal_never_transient() -> None:
    """registry.invoke swallows the exception — the classifier must NOT
    guess TRANSIENT from an opaque TOOL_ERROR (D-2 prerequisite)."""
    kind, signature = classify_failure(
        tool="build_itinerary", ok=False, error_code="TOOL_ERROR"
    )
    assert kind == "INTERNAL"
    assert signature == "INTERNAL:build_itinerary:TOOL_ERROR"


def test_structured_provider_error_survives_the_tool_boundary() -> None:
    """The handler preserves PlanningProviderError's structured code, so a
    provider timeout is classifiable as TRANSIENT end-to-end (this is the
    evidence-preservation half of the D-2 prerequisite)."""
    error = PlanningProviderError(
        "AMap unavailable",
    ) if False else _provider_error("NETWORK_ERROR", "PROVIDER_UNAVAILABLE")
    registry = ToolRegistry.with_runtime(
        ToolRuntime(
            itinerary_builder=_RaisingBuilder(error),
            feasibility=StructuralFeasibilityGate(),
        )
    )
    state = AgentState(slots=_confirmed_slots())
    result, _ = asyncio.run(
        registry.invoke(ToolCall("build_itinerary"), state)
    )
    assert not result.ok
    assert result.error_code == "PROVIDER_UNAVAILABLE"

    kind, signature = classify_failure(
        tool="build_itinerary", ok=False, error_code=result.error_code
    )
    assert kind == "TRANSIENT"


class _RaisingBuilder:
    def __init__(self, error: Exception) -> None:
        self._error = error

    async def __call__(self, *, slots, trip_id=None):
        raise self._error


def _provider_error(category: str, code: str) -> PlanningProviderError:
    from trip_agent.providers.errors import ProviderOperation

    return PlanningProviderError.from_failure(
        _provider_failure(category, code),
        operation=ProviderOperation.POI_SEARCH,
    )


def _provider_failure(category: str, error_code: str):
    from trip_agent.providers.map import ProviderFailure

    return ProviderFailure(
        provider="AMAP",
        error_code=error_code,
        error_message="simulated provider failure",
        category=category,
        operation="POI_SEARCH",
        retryable=False,
        latency_ms=1,
        fetched_at=datetime(2026, 9, 1, tzinfo=UTC),
    )


def _confirmed_slots() -> ConstraintSlots:
    return (
        ConstraintSlots.empty()
        .fill("destination", "成都", state=SlotState.CONFIRMED)
        .fill("start_date", "2026-10-01", state=SlotState.CONFIRMED)
        .fill("end_date", "2026-10-03", state=SlotState.CONFIRMED)
    )


# ── Failure memory (user §十九) ──────────────────────────────────────────────


def test_failure_memory_counts_consecutive_identical_failures() -> None:
    kind, signature = classify_failure(
        tool="build_itinerary", ok=False, error_code="NETWORK_ERROR"
    )
    assert advance_failure_memory(
        kind=kind, signature=signature,
        current_kind=None, current_signature=None, current_attempts=0,
    ) == (kind, signature, 1)
    assert advance_failure_memory(
        kind=kind, signature=signature,
        current_kind=kind, current_signature=signature, current_attempts=1,
    ) == (kind, signature, 2)

    other, other_sig = classify_failure(
        tool="search_place", ok=False, error_code="CAPABILITY_MISSING"
    )
    assert advance_failure_memory(
        kind=other, signature=other_sig,
        current_kind=kind, current_signature=signature, current_attempts=2,
    ) == (other, other_sig, 1)


def test_failure_memory_resets_on_success() -> None:
    kind, signature = classify_failure(tool="build_itinerary", ok=True)
    assert (kind, signature) == (None, "")
    assert advance_failure_memory(
        kind=kind, signature=signature,
        current_kind="TRANSIENT", current_signature="TRANSIENT:build_itinerary:NETWORK_ERROR",
        current_attempts=3,
    ) == (None, None, 0)


# ── End-to-end wiring: a failed build lands in the state memory ─────────────


def test_failed_build_lands_in_state_failure_memory() -> None:
    error = _provider_error("NETWORK_ERROR", "PROVIDER_UNAVAILABLE")
    registry = ToolRegistry.with_runtime(
        ToolRuntime(
            itinerary_builder=_RaisingBuilder(error),
            feasibility=StructuralFeasibilityGate(),
        )
    )
    loop = AgentLoop(decider=AskingDecider(), tools=registry)
    states: list = []

    async def sink(state) -> None:
        states.append(state)

    result = asyncio.run(
        run_agent(loop, AgentState(slots=_confirmed_slots()), checkpoint_sink=sink)
    )
    # D-1 does not change the exit decision (the decider keeps asking for the
    # missing candidate space in its own way) — but the memory IS recorded.
    assert states[-1].failure_kind == "TRANSIENT"
    assert states[-1].failure_attempts >= 1
    assert result.stop_reason in {"WAITING_USER", "CEILING_REACHED"}


# ── Checkpoint compatibility (user §十五) ────────────────────────────────────


def test_checkpoint_v2_round_trips_failure_memory_without_version_bump() -> None:
    from trip_agent.agent.state import agent_state_from_dict, agent_state_to_dict

    state = AgentState(
        slots=_confirmed_slots(),
        failure_kind="TRANSIENT",
        failure_signature="TRANSIENT:build_itinerary:NETWORK_ERROR",
        failure_attempts=2,
    )
    data = agent_state_to_dict(state)
    assert data["version"] == 2  # no version bump: the fields are additive
    restored = agent_state_from_dict(data)
    assert restored.failure_kind == "TRANSIENT"
    assert restored.failure_signature == state.failure_signature
    assert restored.failure_attempts == 2


def test_pre_d1_checkpoint_loads_with_empty_failure_memory() -> None:
    """A v2 checkpoint written before D-1 has no failure keys — it must load
    with defaults (code evidence that no version bump is required)."""
    from trip_agent.agent.state import agent_state_from_dict

    restored = agent_state_from_dict(
        {
            "version": 2,
            "slots": {},
            "observations": [],
        }
    )
    assert restored.failure_kind is None
    assert restored.failure_signature is None
    assert restored.failure_attempts == 0
