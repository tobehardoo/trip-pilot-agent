# Legacy message contracts

Kept for historical reference only.  The Python worker and Java consumer
no longer produce or consume these versions.

| Schema | Superseded by | Reason |
|---|---|---|
| `planning-completed-event-v1` | v2 | No coordinates (Demo-only itinerary) |
| `planning-completed-event-v2` | v3 | No transit legs |
| `planning-completed-event-v3` | v4 | No knowledge evidence |
| `planning-create-command-v1` | v2 | No guide evidence, no extended constraints |

Active versions live in the parent directory (`contracts/messaging/`).
