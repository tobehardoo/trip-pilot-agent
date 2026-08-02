# Messaging contract status

The active planning contracts are:

| Event | Producer | Consumer policy |
| --- | --- | --- |
| `planning-completed-event-v6` | Python | Java reads v1-v6; v7 is rejected |
| `planning-failed-event-v2` | Python | Java reads v1 and v2 |
| `planning-failed-event-v1` | Deprecated | Read-only compatibility for historical infeasible events |
| `planning-completed-event-v7` | None | Draft only; not enabled |

New Python failures use v2 exclusively. Failure v2 carries only safe Provider diagnostics: category/code, provider, operation, retryability/count, fallback flags, safe message, and optional safe Provider code. It must not contain credentials, authorization data, complete Provider requests/responses, user-sensitive input, or stack traces.

Completion v6 has an optional strict `providerProvenance` object. New success producers use it for requested/primary/actual providers, fallback status/reason, and typed operations; Route operations also carry stable Transit/Activity IDs for persistence remapping. Historical v6 without the object remains valid and means unrecorded provenance. Java must not infer missing fields, and v7 remains rejected.

Fixtures in `fixtures/planning-completed-event-v6/` cover legacy, Demo, real-only, explicit mixed fallback, and deliberately reordered multi-Transit mixed results; Python Schema tests and Java parser/persistence tests consume the same files. Schema fixtures in `fixtures/planning-failed-event-v2/` remain shared by both languages. Missing required fields, wrong JSON types, illegal provenance combinations, and unsupported schema versions are rejected.

See [the Provider policy ADR](../../docs/adr/provider-mode-failure-and-fallback-policy.md) and [API contract documentation](../../docs/api.md) for runtime mode, retry, fallback, SSE, and persistence semantics.
