"""E-1 — the deterministic Planning Reflection Decision.

One pure verdict function (:func:`reflect_on_evaluation`) turns the stored
evaluation (``plan_evaluation``) into the loop's reflection verdict, and one
budget predicate (:func:`reflection_budget_exhausted`) bounds how many
evaluation-rejected candidates a single constraint context may produce.

Discipline (Phase E-0 design verdict + Phase E decision contract):

- pure: no I/O, no LLM, no state mutation, no time dependence;
- the verdict reads ONLY the hard-validation channel (``status`` +
  ``failures``).  Quality feedback (``plan_evaluation["quality"]``) is a
  feedback channel, never a gate — a hard-PASS itinerary is a legitimate
  state and must not be blocked by quality (E-0 Fact C);
- ``REFLECTION_MAX_ATTEMPTS`` mirrors the planner's ``MAX_REPAIR_ATTEMPTS``
  (feasibility/repair/engine.py:30): the agent may try, it may not spin;
- the budget counts consecutive rejected candidates under the CURRENT
  constraint context; a user-applied constraint change resets it together
  with the failure memory (tools.py ``update_constraints``).
"""

from __future__ import annotations

from typing import Any, Literal

from trip_agent.agent.state import AgentState

# Same philosophy as the planner's MAX_REPAIR_ATTEMPTS (engine.py:30): a
# bounded number of attempts, then the loop must hand the outcome to the
# user instead of spinning.  Per constraint context.
REFLECTION_MAX_ATTEMPTS = 3

type ReflectionVerdict = Literal["ACCEPT", "REJECT_HARD"]

# A rejected candidate cannot ride to EMITTED on a structural-gate pass; the
# reflection budget stop message is the one final answer Case D may emit.
REFLECTION_EXHAUSTED_ANSWER = (
    "当前约束下反复尝试仍无法生成可接受的行程，"
    "请调整必去地点、日期或预算后重新开始。"
)


def reflect_on_evaluation(evaluation: dict[str, Any] | None) -> ReflectionVerdict:
    """The reflection verdict over the stored hard-validation summary.

    ``None`` (demo path / pre-build state) and any status without unresolved
    failures are ACCEPT — this preserves the pre-Phase-E behaviour exactly.
    Quality feedback never appears here (E-0 Fact C).
    """
    if not isinstance(evaluation, dict):
        return "ACCEPT"
    if evaluation.get("status") == "NEEDS_REPAIR" and evaluation.get("failures"):
        return "REJECT_HARD"
    return "ACCEPT"


def reflection_budget_exhausted(state: AgentState) -> bool:
    """Case D: the current constraint context has exhausted its reflection
    budget while the latest candidate is still evaluation-rejected."""
    return (
        state.reflection_attempts >= REFLECTION_MAX_ATTEMPTS
        and reflect_on_evaluation(state.plan_evaluation) == "REJECT_HARD"
    )
