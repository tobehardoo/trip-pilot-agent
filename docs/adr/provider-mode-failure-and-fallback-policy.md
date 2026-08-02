# ADR: Provider mode, failure, and fallback policy

- Status: Accepted
- Date: 2026-08-01
- Scope: Python planning worker, AMap adapters, messaging failure contract, Java task/SSE/API mapping

## 1. Problem

The former boolean `DEMO_MODE=false` built AMap providers together with whole-plan and route-level Demo fallbacks. A task could therefore succeed with Demo data after a real Provider failure, while callers expected strict real execution. Retryable was also metadata rather than an executed policy, and failure v1 could express only an infeasible itinerary.

## 2. Legacy `DEMO_MODE` risk

Implicit fallback made `SUCCEEDED` ambiguous, could hide authentication or implementation defects, and could make a top-level AMAP result disagree with a Demo Transit. Unrecoverable worker exceptions could also be requeued without a terminal business event.

## 3. Provider modes

- `DEMO_ONLY`: construct only `DemoPlanningProvider`; no AMap key or request.
- `REAL_ONLY`: require an AMap key; construct `AmapPlanningProvider` without `FallbackPlanningProvider` or `DemoRouteProvider`; every failure remains a failure.
- `REAL_WITH_EXPLICIT_FALLBACK`: construct real and Demo providers, but authorize fallback only through `ProviderFallbackPolicy`.

Production defaults to `REAL_ONLY`. Local no-credential development defaults to `DEMO_ONLY`.

## 4. Error taxonomy

`ProviderErrorCategory` is the stable classification: configuration, authentication, permission, quota, rate limit, timeout, network, unavailable, invalid request, no result, unsupported mode, malformed response, data quality, provider adapter, planning infeasible, and internal error. `ProviderFailureDetails` also carries safe error code/message, provider, operation, retryability, retry count, fallback flags, optional safe Provider code, and safe cause type. Keys, authorization data, complete responses, request payloads, and stack traces are excluded.

## 5. Retry policy

`RetryingMapProvider` and `RetryingRouteProvider` share the private `_RetryExecutor`, which is the only retry layer. The default is one call plus at most two retries, bounded exponential backoff, jitter, `Retry-After` support, and a maximum elapsed budget. Tests inject sleeper/clock functions. Only rate limit, timeout, network, unavailable, and selected malformed responses retry; permanent categories never retry even if an adapter labels them retryable.

## 6. Fallback allowlist

Fallback is always denied outside `REAL_WITH_EXPLICIT_FALLBACK`. After retry exhaustion, rate limit, timeout, network, and unavailable failures are allowed by the built-in explicit-mode policy. Quota and malformed response are denied by default and may be added with `PROVIDER_FALLBACK_CATEGORIES`. Configuration, authentication, permission, invalid request, adapter, and internal failures cannot be configured for fallback. Unknown failures default to deny.

## 7. POI local failure

An ordinary `POI_NOT_FOUND` query contributes no candidates and planning may continue when enough other candidates remain. Missing must-visit or fixed business constraints lead to explicit infeasible/failure semantics; the worker does not invent a Demo POI in `REAL_ONLY`.

## 8. Route local failure

`REAL_ONLY` raises a structured route Provider failure and never calls Demo. Explicit fallback may replace only the failed route when policy allows; other Transit records, modes, locks, polylines, and provider sources remain unchanged. Noncritical `NO_RESULT` and unsupported mode use local business handling rather than unconditional whole-plan fallback.

## 9. Mixed result

A route-level explicit fallback sets the affected Transit to `provider=DEMO` and `estimated=true`, preserves successful AMAP records, and aggregates the result provider as `MIXED`. Completion v6 carries optional typed provenance from `PlanningResult`; route operations include stable Transit/Activity identities and safe failure metadata. Java remaps those identities to persisted UUIDs before task API/SSE exposure. Whole-plan fallback uses `PLANNING` or `REPLANNING` with null route identities and remains distinguishable from `DEMO_ONLY`.

## 10. `planning-failed-event-v2`

Python produces failure v2 for infeasible, Provider, and internal planning failures. Required safe fields include event/task/trip/trace IDs, category/code, provider, operation, retryable/retry count, fallback flags, safe message, and optional safe Provider code. Java validates JSON types before binding, persists the terminal event, exposes it through task API/SSE, and creates no itinerary version.

## 11. Completion v6

Successful planning continues to produce completion v6. Its optional `providerProvenance` extension is strict for new producers while keeping historical v6 payloads valid. Java accepts completion v1-v6 and rejects v7; absent provenance stays unrecorded and is never inferred. Provider failures are not encoded as successful completion events, and the v7 draft is not used as a workaround.

## 12. Failure v1 compatibility and exit

Java remains a read-compatible consumer for historical failure v1 and current v2. New Python code writes v2 only. v1 is deprecated and remains in the repository solely for old `NO_FEASIBLE_ITINERARY` messages; it can be removed only after all queues, dead letters, and retained events are beyond the compatibility window.

## 13. Configuration migration

`PROVIDER_MODE` is authoritative. When it is absent, `DEMO_MODE=true` maps to `DEMO_ONLY` and `DEMO_MODE=false` maps to `REAL_ONLY`. Semantically conflicting new/legacy values, illegal mode values, missing real-mode keys, or prohibited fallback categories fail startup. `.env.example` documents local Demo defaults; `compose.prod.yaml` defaults to strict real mode.

## 14. Rollback

Roll back by selecting an explicit stable mode (`DEMO_ONLY` for deterministic local service, `REAL_ONLY` for production) or by reverting the application image and message producer together while Java still reads v1/v2. Do not restore implicit real-to-Demo fallback. No database rollback is required because the implementation reuses `planning_task.error_code/error_message` and `planning_task_event.payload`; Flyway remains at V27.

## Consequences

Strict production failures become visible instead of being converted into Demo success, retry behavior is bounded and testable, and cross-language success/failure semantics are versioned without enabling v7. A legacy `DEMO_ONLY` replan that preserves AMAP Activity sources cannot satisfy the legal provenance combinations; for compatibility it succeeds without provenance and is explicitly treated as unrecorded.
