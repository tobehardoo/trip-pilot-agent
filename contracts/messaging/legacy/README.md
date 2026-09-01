# Legacy message contracts

Kept for historical reference only.  The Python worker and Java consumer
no longer produce or consume these versions.

| Schema | Superseded by | Reason |
|---|---|---|
| `planning-completed-event-v1` | v2 | No coordinates (Demo-only itinerary) |
| `planning-completed-event-v2` | v3 | No transit legs |
| `planning-completed-event-v3` | v4 | No knowledge evidence |
| `planning-completed-event-v4` | v6 | No factImpacts / providerProvenance / evaluation |
| `planning-completed-event-v5` | v6 | Same generation as v4, replaced by v6 |
| `planning-completed-event-v6` | v9 | Added evaluation + provenance, but no authoritative feasibility report |
| `planning-completed-event-v7` | — | **ABANDONED**: transit cost/mode draft, never reached production |
| `planning-completed-event-v8` | v9 | v6 + minimal schedule fields (dayType/kind/timeFixed); deliberately did NOT merge the v7 draft |
| `planning-create-command-v1` | v2 | No guide evidence, no extended constraints |

Moved to `legacy/` in F-3c: v4–v8 completion schemas were fail-closed for the
Java consumer and are no longer produced by the Python worker.

Active versions live in the parent directory (`contracts/messaging/`).
