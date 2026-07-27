# V2.0 Delivery Evidence

Date: 2026-07-27

This record describes capabilities verified from the repository and the local
Compose acceptance environment. It deliberately distinguishes controlled Demo
validation from provider and production-environment validation.

## Delivered capabilities

- Planning progress has a versioned contract, worker-produced stage events,
  idempotent Java persistence, `Last-Event-ID` replay and browser recovery.
  Per-stage duration and task outcome metrics are exported to Prometheus.
- Transit-leg edits persist `TRANSIT` and `TAXI` choices, recalculated duration,
  cost, route-provider metadata, calculation timestamp and stale status in a
  new immutable itinerary version.
- Anonymous itinerary shares are bound to a specific version. Tokens are
  generated with `SecureRandom`, only SHA-256 hashes are stored, public
  responses are redacted, and owner links can be revoked or reissued after
  expiry. A public endpoint limiter protects anonymous reads.
- Version exports provide a UTF-8 `.ics` calendar and a Chinese-capable PDF
  using the embedded Adobe STSong-Light CJK font. The PDF is rendered as part
  of local verification rather than only checked as raw bytes.
- Trip archive/restore and paged, filterable trip search are available through
  the API and the workspace list, including destination search and an archived
  visibility toggle. Archive state is persisted and remains separate from
  current itinerary data.
- Protected internal planning diagnostics expose sanitized failed-task context
  and an idempotent retry for safe failed create tasks.
- Production Compose starts PostgreSQL, Redis, RabbitMQ, Java, Agent API,
  worker, Web and Prometheus. The PostgreSQL and Prometheus images no longer
  rely on Windows-host bind mounts for their initialization/configuration.

## Verified commands

| Area | Command | Result |
| --- | --- | --- |
| Java tests, Flyway and verification | `mvn -q verify` in `apps/travel-server` | Passed (exit 0) |
| Python tests | `python -m pytest --basetemp .tmp/pytest-v2-run` in `apps/agent-service` | 415 passed, 34 skipped |
| Python static checks | `python -m ruff check .` in `apps/agent-service` | Passed |
| Web unit tests | `pnpm test` in `apps/web` | 92 passed across 20 files |
| Web type/build | `pnpm typecheck` and `pnpm build` in `apps/web` | Passed |
| Browser acceptance | `pnpm test:e2e` in `apps/web` | 4 passed |
| Targeted share regression | `mvn -q -Dtest=ItineraryShareFlowIntegrationTest test` | Passed |

The browser suite covers session restoration, itinerary edit preview, planning
stream interruption and duplicate-event recovery, plus a narrow mobile
anonymous-share view.

## Compose acceptance

The local acceptance stack was rebuilt with `IMAGE_TAG=v2-compose-verify` and
all services reached their health checks. `http://127.0.0.1:18081` returned
HTTP 200. Prometheus at `http://127.0.0.1:19091` reported the
`travel-server:8080` target as `up` and recorded
`trippilot_planning_tasks_total` for both `created` and `succeeded` CREATE
tasks after a real Demo planning flow.

The PDF export from that flow was rendered with PDFium. The rendered page
contains the Guangzhou title, Chinese activity labels and the exported day
entries, confirming the CJK font can be rendered by an independent PDF engine.

## Schema additions

- `V23__complete_transit_leg_writeback.sql`
- `V24__create_itinerary_shares.sql`
- `V25__add_trip_archive_and_search_index.sql`

All additions are forward migrations. The Flyway migration test starts from
historical versions and validates the upgrade path through V25.

## External deployment validation

The repository does not contain production domain ownership, TLS certificates,
or real provider credentials. A deployer must still supply the following before
an Internet-facing production release:

- HTTPS termination and `REFRESH_COOKIE_SECURE=true`.
- A strong `INTERNAL_DIAGNOSTICS_TOKEN` (or dedicated diagnostics-token
  configuration), distinct from application credentials.
- Real provider keys and their domain/IP allowlists when `DEMO_MODE=false`.
- Real AMap Web JS key/security-code validation in the final browser domain.

These are external acceptance prerequisites, not claims made by Demo-mode test
results.
