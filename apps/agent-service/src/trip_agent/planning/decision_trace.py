"""V2 P0-C — in-process decision traces (audit §16.3).

A :class:`DecisionTrace` records a real planning decision (which transport
mode a leg uses, which candidates a tight budget demoted) together with the
evidence that drove it, so the plan can answer *why* — not only *what*.

Traces are planning-process-only: they travel on ``PlanningResult`` and are
never serialized into messaging, persistence, or API surfaces.  The evaluator
converts them into user-facing ``DecisionExplanation`` records, which finally
wires the existing but so-far-unused reason-code vocabulary
(``TRANSIT_MODE`` / ``BUDGET_CONSTRAINT``) to real decisions.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DecisionEvidence:
    """A single verifiable fact behind a decision (key/label/value triple)."""

    key: str
    label: str
    value: str


@dataclass(frozen=True, slots=True)
class DecisionTrace:
    """One planner decision with its reason codes and evidence."""

    subject_type: str
    subject_id: str | None
    summary: str
    reason_codes: tuple[str, ...]
    reasons: tuple[str, ...]
    evidence: tuple[DecisionEvidence, ...]
