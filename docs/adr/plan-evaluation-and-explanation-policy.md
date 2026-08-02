# ADR: Plan evaluation and explanation policy

- Status: Accepted
- Date: 2026-08-02
- Scope: Python planning worker, completion v6, Java task event persistence/API/SSE, Vue trip details

## 1. Problem

A technically valid itinerary did not expose a stable quality score, structured risks, or auditable reasons for important choices. Free-form model explanations would not be reproducible and could claim evidence that is absent from the plan. Quality metadata also has to survive message parsing, persistence, task lookup, SSE replay, and legacy records without changing the completion schema version.

## 2. Decision

Successful create/replan results are evaluated by `PlanEvaluator` before completion v6 is published. The evaluator is rule-based, read-only, and has no LLM or Provider dependency. It receives the frozen planning command and immutable `PlanningResult`; time is supplied through an injectable clock.

The optional completion v6 `evaluation` object has `schemaVersion=1` and an independent `evaluatorVersion` such as `rule-v1`. This allows scoring policy changes without enabling completion v7. New producers write evaluation; Java and Web remain read-compatible with historical v6 events where it is absent.

## 3. Scoring

All dimensions use integer scores from 0 to 100. Overall score is the weighted sum rounded half-up with an integer numerator, so Python and Java produce the same result at `.5` boundaries:

- constraint satisfaction: 30%
- time feasibility: 25%
- budget fit: 15%
- route efficiency: 15%
- interest match: 15%

Weights and warning thresholds are centralized in `evaluation/rules.py`. A warning must not be the only observable effect of a material score risk: deductions must remain visible after weighting and integer rounding. Interest match stays a documented baseline until activities have reliable category tags.

## 4. Completion and failure boundary

Evaluation describes successful, feasible plans only. Budget overflow, trip-date violations, or uncovered fixed appointments produce a structured `DATA_QUALITY_ERROR` and block completion. Failure events never contain evaluation. `feasible=false` is illegal in completion evaluation.

## 5. Warnings and explanations

Warnings use stable codes, severities, entity types/IDs, metrics, actual values, and thresholds. Explanations are deterministic statements backed by plan facts such as fixed appointments, must-visit coverage, route mode, Provider fallback, and grouping. A fixed appointment is covered only when a normalized place name and its complete time window both match an activity. Reasons must not invent facts or call an LLM.

Provider fallback warnings and decisions use the same source Transit identity as provenance. During Java persistence, explicit Activity and Transit reference maps cover single-activity days, impacted replan dates, and unchanged replan dates before the terminal JSONB event is written. GET task responses and SSE/`Last-Event-ID` replay therefore expose the same persisted identities.

## 6. Persistence and compatibility

Evaluation remains in `planning_task_event.payload`; no new relational table or Flyway migration is required. `PlanningTaskService` reads it into typed response data. A missing/null node means legacy success and returns `null`; an invalid stored evaluation fails fast instead of being silently presented as legacy.

The Web displays evaluation only for successful tasks with an itinerary. Successful legacy tasks show an explicit compatibility message. Failed/cancelled tasks do not show a score or legacy message.

## 7. Verification

The repository contains eight deterministic benchmark scenarios: clean real data, near-budget, estimated Transit, fixed appointment, high daily load, long walking, mixed Provider fallback, and tight transfer. The runner uses a frozen clock and checks score ranges plus required/forbidden warning codes. Shared completion fixtures are parsed by both Pydantic and the Java consumer; Parser, PostgreSQL API/SSE, and Web component tests cover the cross-language boundary.

## 8. Versioning and rollback

A scoring or explanation behavior change increments `evaluatorVersion` and updates benchmark expectations and shared fixtures. A wire-shape breaking change increments evaluation `schemaVersion` and requires producer/consumer/Web compatibility tests.

Rollback removes evaluation generation/display while retaining optional-field readers. Existing JSONB events remain readable; no database rollback is required. Do not reinterpret missing evaluation as score zero or infer a historical score from itinerary fields.

## Consequences

Users receive deterministic, explainable quality information and explicit uncertainty. The system accepts the maintenance cost of versioned rules, benchmark baselines, shared fixtures, and identity remapping. Semantic interest matching remains intentionally limited until the domain model supplies trustworthy activity categories.
