# Phase E-0 · Acceptance Summary

**Phase:** E-0 — Evaluation & Decision Audit (AUDIT ONLY, zero code changes)
**Date:** 2026-08-31 · **Base:** HEAD `7ef8340` (D-Final complete)
**Deliverables:** [01-fact-verification.md](./01-fact-verification.md) · [02-design-verdict.md](./02-design-verdict.md)

---

## 1. Scope adherence

| Requirement | Status |
|---|---|
| Zero production-code changes | PASS — `git diff --stat` shows no `src/` or `tests/` modifications |
| Facts A–H re-verified at HEAD with fresh file:line evidence | PASS — no old audit report reused as evidence |
| Fact E measured by running a real counterfactual, not inferred | PASS — throwaway script executed S1/S2/S3 through the real `run_agent` chain; script deleted after measurement |
| Design Verdict answers all 5 mandated questions | PASS — Q1 PASSIVE MEMORY; Q2 three gaps; Q3 extend `plan_evaluation`, no new model; Q4 no new State fields; Q5 no new Decision vocabulary |
| No implementation performed | PASS — E-1 direction recorded as recommendation only |

## 2. Core finding (one line)

> `plan_evaluation` is **PASSIVE MEMORY**: produced and persisted, but no decision
> branch reads it. EMITTED (graph.py:718-721) keys on the STRUCTURAL gate alone, and
> measured S2 shows an unresolved hard-validation FAIL can still be EMITTED — the
> gate/validation divergence has no adjudication rule today.

## 3. Measured evidence highlights

- **S1** Hard PASS + visibly low quality (3 days × one 1-hour activity) → **EMITTED**,
  failure memory cleared, zero quality judgment anywhere. Quality blindness is real,
  not hypothetical.
- **S2** Hard FAIL (BUDGET_EXCEEDED) recorded in `plan_evaluation` while structural
  gate passes → **still EMITTED**, final memory
  `USER_CONSTRAINT / USER_CONSTRAINT:validate_itinerary:BUDGET_EXCEEDED / 1`. New
  sharper finding beyond prior audits.
- **S3** Structural block → WAITING_USER with FEASIBILITY kind and D-4 escalation —
  the ONLY Evaluation-adjacent signal that steers recovery.

## 4. STOP-condition check

No STOP condition triggered: no wire-contract change, no schema change, no new
Coordinator, no constraint mutation, no LLM introduced, no loop-inflation, and the
audit's counterfactual kept loop/tool counts at their natural values (S1/S2: 2 tool
calls each).

## 5. Handoff to E-1

Recommended E-1 cut (authorization required before any implementation):

1. Deterministic quality summary produced where `_hard_validation_summary` already
   runs (itinerary_builder.py:243-267), carried on `BuiltItinerary`.
2. Extend `plan_evaluation` in place with the quality sub-structure — no new field,
   no new model.
3. Make graph.py:718-721 condition on the Evaluation verdict (this also resolves S2).
4. Quality failures classify through the existing `classify_failure` machinery;
   no automatic quality-REPLAN; the existing ASK_USER/STOPPED exits are reused.

## 6. Verdict

**ACCEPT.** E-0 is complete as an audit-only cut: facts verified at HEAD with
line-level evidence, counterfactual measured on the real chain, design verdict
recorded with the mandated five answers, zero code touched. **Awaiting E-1
authorization before any implementation.**
