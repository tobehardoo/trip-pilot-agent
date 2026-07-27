# Planning Progress Contract

## Status

The planning progress transport is implemented for the asynchronous planning
workflow. It is not a timer-driven UI indicator: a worker emits a progress
event only when it crosses an observed processing boundary.

## Message Flow

```text
Python worker
  -> trip.event.exchange / planning.progress
  -> planning.progress.queue
  -> Java contract parser and idempotent consumer
  -> business.planning_task_event
  -> existing task SSE stream with Last-Event-ID replay
  -> Vue planning progress panel
```

The schema lives at
`contracts/messaging/planning-progress-event-v1.schema.json`.
The immutable envelope contains `eventType`, `schemaVersion`, `eventId`,
`traceId`, `taskId`, `tripId`, and `occurredAt`. Its payload contains:

- `stage`: one standardized processing stage.
- `sequence`: a per-task monotonically increasing event sequence.
- `progress`: a stage-boundary completion value from 0 through 100.
- `message`: the user-visible status for the observed boundary.
- `statistics`: an optional bounded map of non-negative integer counters.

`progress` is derived from the stage boundary, never from elapsed time. A
provider may skip unsupported stages. The UI displays those stages as `not
used` instead of presenting fabricated completion.

## Stages

The V1 event schema supports `TASK_ACCEPTED`, `CONTEXT_VALIDATING`,
`CITY_FACTS_LOADING`, `POI_RECALLING`, `CANDIDATES_RANKING`,
`ROUTES_CALCULATING`, `CONSTRAINTS_SOLVING`, `KNOWLEDGE_RETRIEVING`,
`RESULT_EXPLAINING`, and `RESULT_PERSISTING`.

The worker emits the stages for its actual execution path. The AMap provider
reports POI, ranking, routing, and constraint-solving boundaries. The Demo
provider reports its actual constraint-solving path without claiming POI or
route calls it did not make. Local replanning reports only its local context,
routing, explanation, and persistence work.

## Delivery Semantics

Progress event IDs are deterministically derived from the planning command ID
and stage. Redelivery therefore reaches the Java consumer idempotently. The
consumer validates task and trace identity, rejects non-increasing sequences,
changes a queued task to `RUNNING` at its first accepted progress event, and
persists the event before publishing it to the existing SSE hub.

Terminal `PLANNING_COMPLETED`, `PLANNING_FAILED`, and `PLANNING_CANCELLED`
events remain the source of terminal task state. Progress remains visible in
the task-event replay history after the terminal event.

## Verification

- Java parser, listener, and PostgreSQL integration tests cover validation,
  idempotency, state transition, and sequence rejection.
- Python contract and AMQP tests cover real stage order, progress values, and
  terminal publication ordering.
- Vue tests cover rendering the stage supplied by SSE data and showing skipped
  stages honestly.

Stage-duration metrics and browser-level SSE recovery remain V2 follow-up
work and are tracked in the V2 delivery checklist.
