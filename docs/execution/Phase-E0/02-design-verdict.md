# Phase E-0 · Design Verdict — Evaluation & Decision

**Audit target:** HEAD (`7ef8340`, D-Final complete) · **Mode:** read-only, zero code changes
**Evidence base:** [01-fact-verification.md](./01-fact-verification.md) (Facts A–H, measured counterfactual S1/S2/S3)

---

## Verdict — the five mandated questions

### Q1. What is Evaluation today?

**PASSIVE MEMORY — with one classification side-channel.**

`plan_evaluation` is produced by `RealItineraryBuilder._hard_validation_summary`
(itinerary_builder.py:243-267) as `{"status", "failures":[{rule_id, reason_code, message}]}`
and stored into state by the `build_itinerary` tool (tools.py:579-586, state.py:301).
It is consumed in exactly two ways:

1. **Question text** — `_failure_detail` reads `plan_evaluation.failures[*].message`
   only to compose the ASK_USER message (graph.py:404-424). It never reads `status`,
   never changes a branch.
2. **Classification side-channel** — `_act_node` extracts the same `reason_codes`
   directly from the tool observation (not from `plan_evaluation` state) and feeds
   `classify_failure(ok=True, validation_reason_codes=...)` (graph.py:692-706,
   failure_policy.py:190-204). This is the only place a validation failure steers
   recovery — and it comes from the OBSERVATION, not from the stored Evaluation.

AskingDecider's decision branches (graph.py:177-361) read observations, candidate
presence, failure memory, and slots — never `plan_evaluation`. Measured: S1 (hard
PASS + visibly low quality) → EMITTED with zero quality judgment; S2 (hard FAIL
recorded, gate passes) → still EMITTED. Evaluation does not participate in the
decision. Verdict: **PASSIVE MEMORY**.

### Q2. What does Phase E truly lack?

Three gaps, in order of severity:

1. **No quality producer at the agent boundary.** Quality scoring exists only inside
   the pipeline (`candidates.py:188-262 _score`; amap provider). Nothing crosses the
   `BuiltItinerary` boundary except the hard-validation status. The agent has zero
   quality signal — not even a low one.
2. **No Evaluation → Decision branch.** The single emission point
   (graph.py:718-721) conditions EMITTED on `observation.tool == "validate_itinerary"
   and observation.ok` — the STRUCTURAL gate only. There is no branch that consults
   `plan_evaluation` before emitting.
3. **Gate / hard-validation divergence is unadjudicated.** S2 proved a candidate can
   carry an unresolved hard-validation FAIL (BUDGET_EXCEEDED) and still be EMITTED,
   because the structural gate (feasibility_gate.py:29-68, 4 checks only) is
   deliberately narrower than hard validation. Which verdict governs emission is not
   decided by any rule today — it is an accident of check ordering.

### Q3. Is a new Evaluation model needed?

**No. Priority order applied: existing sufficient > extend existing > new field > new model.**

- `plan_evaluation: dict[str, Any] | None` (state.py:301) is already the Evaluation
  carrier, already checkpoint-round-trips (state.py:408/472), and already carries a
  `status` + `failures` structure.
- **Extend, don't create:** E-1 should add a quality sub-structure (e.g.
  `plan_evaluation["quality"] = {"score", "verdict", "reasons"}`) and/or promote
  `status` to an explicit overall `verdict`. Same field, same round-trip, no
  migration, no new model class.
- `BuiltItinerary` (itinerary_builder.py:201-213) is the natural place to attach the
  quality summary inside the builder, mirroring how `feasibility` already travels.

Rejected: a new `Evaluation` pydantic model or new state field — both would duplicate
an already-wired carrier.

### Q4. Are new State fields needed?

**No.** `plan_evaluation` (quality + hard status), `candidate_itinerary`,
`decision_summaries`, and the failure-memory triple already cover every piece of
information an Evaluation-driven decision needs:

- quality verdict → inside `plan_evaluation`;
- retry/escalation accounting → existing `failure_kind` / `failure_signature` /
  `failure_attempts` (state.py:307-309) with D-1/D-2/D-4 semantics intact;
- checkpoint v2 already round-trips `plan_evaluation` — no persistence change.

Adding a field is forbidden here because an existing one suffices (user §decision
priority).

### Q5. Are new Decisions needed?

**No.** The existing exit vocabulary is sufficient; E-1 changes WHICH inputs pick
them, not the vocabulary:

- **EMITTED** — keep, but make graph.py:718-721 condition on the Evaluation verdict,
  not only on the structural gate.
- **Quality FAIL** → reuse the existing REPAIR path: a quality failure is classified
  through `classify_failure` exactly like a hard-validation failure (USER_CONSTRAINT
  family for budget-style reasons), so the existing REPLAN-via-question machinery
  (D-3, D-4) handles it — the user stays the only one who may change confirmed
  constraints.
- **No automatic quality-REPLAN** (Fact F boundary): a quality shortfall escalates
  to ASK_USER or STOPPED per `_STOPS_NOT_ASKS` / `USER_OWNED_KINDS`, never to an
  autonomous rebuild.

---

## Implementation direction for E-1 (not executed here)

1. **Producer:** deterministic quality evaluation inside the builder/gate boundary —
   prefer computing the quality summary where `_hard_validation_summary` already runs
   (itinerary_builder.py:243-267), so the real path gets it with zero new I/O.
   Demo path stays None (Fact A-7); do not invent a demo quality scorer.
2. **Decision branch:** extend the EMITTED condition at graph.py:718-721 to also
   require the Evaluation verdict to be acceptable; an unacceptable verdict routes to
   the existing failure-classification path (observation carries the reasons), not to
   a new exit.
3. **Adjudicate S2:** hard-validation FAIL must not ride to EMITTED on a structural
   gate pass. E-1's branch order is the fix: Evaluation verdict dominates emission.
4. **Deterministic first** (Fact H): AskingDecider stays the default; quality rules
   are code, not LLM judgment. StructuredOutputDecider's prompt (graph.py:600-622)
   may later be EXTENDED to see plan_evaluation, never to own the decision.

## Invariants E-1 must keep

- EMITTED remains deterministic code, never an LLM tool.
- Confirmed user constraints stay immutable; a quality failure asks, never edits.
- No wire-contract changes, no schema changes, no new Coordinator/Worker split.
- The bounded loop (MAX_STEPS=8 / MAX_TOOL_CALLS=16 / MAX_LLM_CALLS=8, graph.py:44-46)
  is untouched — quality evaluation adds no extra tool call (it rides on the existing
  build/validate observations).
- Evaluation ≠ hard validation (Fact C): quality LOW on a hard-PASS itinerary is a
  legitimate state, and must be recorded as quality, not mislabeled as a hard failure.
