# Guide Intelligence Import V1 Test Plan

## Scope

This slice lets an authenticated traveler submit one public HTTPS guide URL for a trip. The
system fetches the page through the existing SSRF-safe acquisition gateway, extracts readable
content and travel facts, records source and freshness metadata, and exposes the result only to
the trip owner.

It deliberately does not log in to third-party sites, bypass anti-bot controls, solve CAPTCHAs,
or crawl accounts/search results in bulk.

## Acceptance criteria

1. A trip owner can import a public HTTPS article and see its title, source, fetch time, excerpt,
   facts, confidence, and expiry time.
2. Re-importing the same final URL and content for the same trip is idempotent while refreshing
   fetch, observation, and expiry metadata.
3. Another user receives `404 TRIP_NOT_FOUND` and cannot list or create imports for the trip.
4. HTTP, credential-bearing URLs, localhost, private/reserved IPs, unsafe DNS answers, cross-domain
   redirects, oversized responses, and unsupported compressed responses are rejected.
5. The agent API is not published to the host and requires a shared internal token.
6. Failed extraction never fabricates facts; an article with no supported travel facts is stored
   with an empty fact list and a clear excerpt.
7. Extraction caps readable content at 100,000 characters, individual facts at 1,000 characters,
   and each response at 100 facts; POST imports are rate-limited at the edge.

## Test matrix

| Layer | Cases |
| --- | --- |
| Python unit | Generic article extraction, navigation/script removal, classification, deduplication, category TTL, empty-fact behavior |
| Python service | Safe fetch adapter, deterministic content hash, source/final URL propagation, fetch failures |
| Python API | Internal-token rejection, request validation, successful response contract |
| Java integration | Authenticated create/list, ownership isolation, URL validation, idempotent persistence, downstream error mapping |
| Web component | URL submission, loading/error states, source/freshness/fact rendering |
| E2E | Register, create trip, import controlled public fixture, confirm persisted evidence after reload |
| Security regression | SSRF policy tests and no agent API host port |

## Coverage and release gates

- Python changed modules: at least 80% line coverage.
- Java bundle: existing JaCoCo 80% gate remains green.
- Web: existing Vitest suite plus guide-import component tests.
- Ruff, Maven verify, TypeScript build, and production Compose health checks must pass.
