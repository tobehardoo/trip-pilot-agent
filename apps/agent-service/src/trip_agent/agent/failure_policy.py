"""V3 D-1/D-4 — failure classification and repetition judgement.

One pure entry point: :func:`classify_failure` turns a tool observation
(structured fields only — error code, conflict codes, validation reason
codes) into a :class:`FailureKind` and a stable :func:`failure_signature`;
:func:`advance_failure_memory` folds that into the run's failure memory.

Discipline (Phase D-0 §08):

- pure: no I/O, no LLM, no state mutation, no time dependence;
- classification is decided by STRUCTURED evidence (error codes, conflict
  codes, validation reason codes) — never by substring-matching free text;
- a swallowed exception cannot be recovered: an opaque ``TOOL_ERROR``
  classifies as INTERNAL, never guessed as TRANSIENT (D-2 prerequisite:
  handlers must preserve the structured provider error at the boundary);
- D-1 only understands failures; D-4 adds the one judgement the decider
  needs on top of classification — whether repeating the action that just
  failed would be recovery or a policy loop
  (:func:`escalate_duplicate`, :data:`FAILURE_REPEAT_BUDGET`).
"""

from __future__ import annotations

from typing import Any, Literal

from trip_agent.providers.errors import TRANSIENT_CATEGORIES

type FailureKind = Literal[
    "TRANSIENT",
    "CAPABILITY_MISSING",
    "USER_CONSTRAINT",
    "CANDIDATE_EMPTY",
    "FEASIBILITY",
    "VALIDATION",
    "INTERNAL",
]

# Provider/tool error codes whose recovery candidate is a bounded retry.
# The bare category values derive from providers/errors.py
# ``TRANSIENT_CATEGORIES``; the prefixed ``PROVIDER_*`` forms are the
# ``ProviderErrorCode`` values the production boundary (tools.py) surfaces
# verbatim (providers/map.py:76-88) — a real timeout, rate limit or quota
# exhaustion arrives prefixed, not as the bare category value.
# ``PROVIDER_ERROR`` is deliberately absent: its category is
# INVALID_REQUEST/PROVIDER_ADAPTER_ERROR (retryable=False), a deterministic
# failure, not a transient one.  ``TIMEOUT_ERROR`` is the planning-layer
# spelling of a timeout.
_TRANSIENT_CODES = frozenset(
    {
        *(category.value for category in TRANSIENT_CATEGORIES),
        "TIMEOUT_ERROR",
        "PROVIDER_TIMEOUT",
        "PROVIDER_RATE_LIMITED",
        "PROVIDER_QUOTA_EXHAUSTED",
    }
)

# Deterministic planning-refusal codes: the constraints themselves cannot
# be satisfied, so the recovery candidate is the user.
_INFEASIBLE_CONFLICT_KINDS: dict[str, FailureKind] = {
    "MUST_VISIT_UNAVAILABLE": "USER_CONSTRAINT",
    "MUST_VISIT_UNVERIFIABLE_IN_DEMO": "USER_CONSTRAINT",
    "TRAVEL_ANCHOR_UNAVAILABLE": "USER_CONSTRAINT",
    "INSUFFICIENT_DAY_CAPACITY": "FEASIBILITY",
    "FIXED_SCHEDULE_OVERLAP": "FEASIBILITY",
}

# Hard-validation reason codes (run_validation rule failures) mapped to the
# failure kind — the reason decides, the rule id only feeds the signature.
_VALIDATION_REASON_KINDS: dict[str, FailureKind] = {
    "MUST_VISIT_PLACE_MISSING": "USER_CONSTRAINT",
    "BUDGET_EXCEEDED": "USER_CONSTRAINT",
    "TRIP_DATE_RANGE": "FEASIBILITY",
    "FIXED_SCHEDULE_COVERAGE": "FEASIBILITY",
    "ACTIVITY_OVERLAP": "FEASIBILITY",
    "ROUTE_ENDPOINT_CONTINUITY": "FEASIBILITY",
    "CROSS_DAY_CONTINUITY": "FEASIBILITY",
    "OPENING_HOURS": "FEASIBILITY",
    "VISIT_DURATION": "FEASIBILITY",
    "MEAL_WINDOW": "FEASIBILITY",
    "DUPLICATE_POI": "FEASIBILITY",
}

_CANDIDATE_EMPTY_CODES = frozenset(
    {
        "INSUFFICIENT_AMAP_POIS",
        "NO_RESULT",
        "CANDIDATE_EMPTY",
    }
)

# Input problems the USER can fix by rephrasing/re-supplying a value.
_USER_INPUT_CODES = frozenset(
    {
        "INVALID_VALUES",
        "INVALID_REJECTIONS",
        "NO_VALUES",
        "EMPTY_KEYWORD",
        "EMPTY_PLACE",
        "EMPTY_QUERY",
        "EMPTY_QUESTION",
        "INCOMPLETE_ROUTE",
        "INVALID_CONSTRAINT_VALUES",
        "INCOMPLETE_CONSTRAINTS",
        "NO_CANDIDATE",
        "NO_PREFERENCES",
        "PROFILE_UNAVAILABLE",
    }
)

# Codes that must never be guessed into a friendlier kind.
_INTERNAL_CODES = frozenset(
    {
        "TOOL_ERROR",
        "UNKNOWN_TOOL",
        "INTERNAL_ERROR",
        "INTERNAL_PLANNING_FAILED",
        "MALFORMED_RESPONSE",
        "PROVIDER_ADAPTER_ERROR",
        "INVALID_REQUEST",
        "CONFIGURATION_ERROR",
        "AUTHENTICATION_ERROR",
        "PERMISSION_DENIED",
        "DATA_QUALITY_ERROR",
    }
)


def _kind_for_error_code(error_code: str) -> FailureKind:
    if error_code == "CAPABILITY_MISSING":
        return "CAPABILITY_MISSING"
    if error_code == "PLANNING_INFEASIBLE":
        # No structured conflict codes reached the classifier: the default
        # recovery candidate for an infeasible plan is the user, but the
        # signature stays coarse (see _failure_signature).
        return "USER_CONSTRAINT"
    if error_code in _TRANSIENT_CODES:
        return "TRANSIENT"
    if error_code in _CANDIDATE_EMPTY_CODES:
        return "CANDIDATE_EMPTY"
    if error_code == "FEASIBILITY_BLOCKED":
        return "FEASIBILITY"
    if error_code in _USER_INPUT_CODES:
        return "USER_CONSTRAINT"
    if error_code in _INTERNAL_CODES:
        return "INTERNAL"
    return "INTERNAL"


def _failure_signature(
    kind: FailureKind, *, tool: str, error_code: str | None, detail: str
) -> str:
    """Deterministic, bounded signature: same failure → same signature.

    Composed of the kind, the tool, and the most specific STRUCTURED detail
    available (error code / conflict code / validation reason code).  Never
    timestamps, exception reprs or stack traces.
    """
    detail_part = f":{detail}" if detail else ""
    return f"{kind}:{tool}{detail_part}"


def classify_failure(
    *,
    tool: str,
    ok: bool,
    error_code: str | None = None,
    data: Any = None,
    validation_reason_codes: tuple[str, ...] = (),
) -> tuple[FailureKind | None, str]:
    """Classify one tool observation.

    Returns ``(FailureKind, signature)``; ``(None, "")`` for a successful
    observation (the failure memory resets on success).  Priority is decided
    by the structured evidence, in this order:

    1. success without validation failures → no failure;
    2. validation reason codes (a successful build whose hard validation
       failed) → kind per reason, signature from ALL reason codes;
    3. CAPABILITY_MISSING (misconfiguration is never anything else);
    4. PLANNING_INFEASIBLE, subdivided by the structured conflict codes —
       user-constraint refusals, geometry refusals, or (without codes)
       the coarse USER_CONSTRAINT default;
    5. transient provider codes;
    6. candidate-empty codes;
    7. user-input codes;
    8. everything else (including opaque TOOL_ERROR) → INTERNAL.
    """
    if ok:
        if validation_reason_codes:
            kinds = [
                _VALIDATION_REASON_KINDS.get(code, "VALIDATION")
                for code in validation_reason_codes
            ]
            kind = kinds[0]
            signature = _failure_signature(
                kind,
                tool=tool,
                error_code=None,
                detail=":".join(sorted(set(validation_reason_codes))),
            )
            return kind, signature
        return None, ""

    code = error_code or "UNKNOWN"
    if code == "CAPABILITY_MISSING":
        return "CAPABILITY_MISSING", _failure_signature(
            "CAPABILITY_MISSING", tool=tool, error_code=None, detail=""
        )

    if code == "PLANNING_INFEASIBLE":
        conflict_codes = _conflict_codes(data)
        if conflict_codes:
            kinds = {
                _INFEASIBLE_CONFLICT_KINDS.get(code, "FEASIBILITY")
                for code in conflict_codes
            }
            # Deterministic pick: the first kind in taxonomy order that any
            # conflict maps to (a single planning refusal normally carries
            # exactly one conflict).
            for candidate in ("USER_CONSTRAINT", "FEASIBILITY", "CANDIDATE_EMPTY"):
                if candidate in kinds:
                    kind = candidate
                    break
            else:
                kind = "FEASIBILITY"
            signature = _failure_signature(
                kind,
                tool=tool,
                error_code="PLANNING_INFEASIBLE",
                detail=":".join(sorted(conflict_codes)),
            )
            return kind, signature
        return "USER_CONSTRAINT", _failure_signature(
            "USER_CONSTRAINT",
            tool=tool,
            error_code="PLANNING_INFEASIBLE",
            detail="PLANNING_INFEASIBLE",
        )

    if code in _TRANSIENT_CODES:
        return "TRANSIENT", _failure_signature(
            "TRANSIENT", tool=tool, error_code=code, detail=code
        )
    if code in _CANDIDATE_EMPTY_CODES:
        return "CANDIDATE_EMPTY", _failure_signature(
            "CANDIDATE_EMPTY", tool=tool, error_code=code, detail=code
        )
    if code == "FEASIBILITY_BLOCKED":
        return "FEASIBILITY", _failure_signature(
            "FEASIBILITY", tool=tool, error_code=code, detail=""
        )
    if code in _USER_INPUT_CODES:
        return "USER_CONSTRAINT", _failure_signature(
            "USER_CONSTRAINT", tool=tool, error_code=code, detail=code
        )
    return "INTERNAL", _failure_signature(
        "INTERNAL", tool=tool, error_code=code, detail=code or "unknown"
    )


def _conflict_codes(data: Any) -> tuple[str, ...]:
    """Structured conflict codes from a failure observation's data, if the
    handler preserved them (V3 D-1: providers raise with conflicts)."""
    if not isinstance(data, dict):
        return ()
    codes = data.get("conflict_codes") or ()
    return tuple(str(code) for code in codes)


def advance_failure_memory(
    *,
    kind: FailureKind | None,
    signature: str,
    current_signature: str | None,
    current_attempts: int,
) -> tuple[str | None, str | None, int]:
    """Fold one classified observation into the failure memory.

    Semantics (D-1 records; D-4 will act): ``failure_attempts`` counts the
    CONSECUTIVE occurrences of the same failure signature.  A different
    signature restarts at 1; a success resets the memory entirely.
    """
    if kind is None or not signature:
        return None, None, 0
    if signature == current_signature:
        return kind, signature, current_attempts + 1
    return kind, signature, 1


# ── V3 D-4: the repetition judgement on top of the D-1 classification ───────

# D-2 authorizes ONE automatic retry plus the rebuilds the user explicitly
# asks for by replying to the transient-failure notice.  Past that, repeating
# the same transient failure is a policy loop, not recovery.
MAX_TRANSIENT_SAME_FAILURE_ACTIONS = 3

# How many CONSECUTIVE same-signature failures of a kind still count as
# progress.  ``0`` means the first failure already forbids repeating the same
# action: for a deterministic refusal (same input ⇒ same output) a second
# attempt carries zero information.
FAILURE_REPEAT_BUDGET: dict[FailureKind, int] = {
    "TRANSIENT": MAX_TRANSIENT_SAME_FAILURE_ACTIONS,
    "CAPABILITY_MISSING": 0,
    "USER_CONSTRAINT": 0,
    "CANDIDATE_EMPTY": 0,
    "FEASIBILITY": 0,
    "VALIDATION": 0,
    "INTERNAL": 0,
}

# Kinds the user cannot rescue by answering: a stale provider outage, an
# opaque internal error, a missing capability.  Everything else escalates to
# a question instead of a stop.
_STOPS_NOT_ASKS: frozenset[FailureKind] = frozenset(
    {"TRANSIENT", "INTERNAL", "CAPABILITY_MISSING"}
)

# The kinds whose escalation is a question, therefore the kinds whose reply
# must be read as a possible constraint adjustment: only the user can change
# the outcome of one of these failures, so the decider parses their resume
# message before it considers repeating the failing action (D-4).
USER_OWNED_KINDS: frozenset[FailureKind] = frozenset(
    kind for kind in FAILURE_REPEAT_BUDGET if kind not in _STOPS_NOT_ASKS
)

type Escalation = Literal["ASK_USER", "STOPPED"]


def signature_tool(signature: str | None) -> str | None:
    """The tool segment of a ``KIND:tool:detail`` signature (``None`` if absent).

    Because the failing tool is embedded in the signature, "the action I am
    about to issue is the action that just failed" needs no extra state field.
    """
    if not signature:
        return None
    parts = signature.split(":")
    return parts[1] if len(parts) > 1 and parts[1] else None


def escalate_duplicate(
    *,
    kind: str | None,
    signature: str | None,
    attempts: int,
    action_tool: str,
) -> Escalation | None:
    """Is issuing ``action_tool`` now recovery, or the same loop again?

    Returns the escalation the decider must take INSTEAD of the action, or
    ``None`` when the action is still policy-approved.  Three conditions must
    hold together (attempts alone is never sufficient):

    - the action targets the tool that just failed (same action);
    - the failure memory is unresolved and past its kind's repeat budget
      (same failure, no progress — and because any applied constraint change
      or any successful observation resets the memory, being past the budget
      also proves no new information arrived);
    - the kind is known.

    Never mutates state: the guard only says "do not send this action", the
    decider owns the exit.
    """
    if kind is None or not signature or attempts <= 0:
        return None
    if signature_tool(signature) != action_tool:
        return None
    budget = FAILURE_REPEAT_BUDGET.get(kind)
    if budget is None or attempts <= budget:
        return None
    return "STOPPED" if kind in _STOPS_NOT_ASKS else "ASK_USER"
