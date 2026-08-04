# P0 Local Real AMap Validation

Date: 2026-07-30

Scope: isolated local Compose environment only; this is not a substitute for final HTTPS-domain acceptance.

## Results

- Ran the complete Compose stack with `DEMO_MODE=false` and all long-running services healthy.
- Created an isolated test account and trip, then synchronized Guangzhou city intelligence.
- Verified real AMap weather and POI responses: names, coordinates, addresses, and operating information reached the itinerary workflow with `AMAP` provider metadata.
- Generated a six-place itinerary. Longer legs were recommended as public transit, while a 16-minute short leg remained walking.
- Confirmed the AMap JavaScript map showed its base layer, route and six markers after a page refresh.
- Browser verification ended with zero errors. A Canvas2D performance hint emitted by the third-party AMap SDK remains as a non-blocking warning.

## CSP Remediation

The first real browser run found that the AMap SDK telemetry script and Blob Worker were blocked by the web CSP. The production Nginx policy now permits only the required `https://restapi.amap.com` script origin and `worker-src 'self' blob:`. The policy is covered by `nginx-config.test.ts`.

## Remaining Release Gate

The browser Key was validated on `localhost`. Final P0 release approval still requires the target HTTPS domain, its AMap allow-list configuration, isolated staging infrastructure, alert routing, key-rotation rehearsal, and rollback evidence.
