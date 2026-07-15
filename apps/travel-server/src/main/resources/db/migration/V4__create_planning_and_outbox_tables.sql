CREATE TABLE business.planning_task (
    id UUID PRIMARY KEY,
    trip_id UUID NOT NULL REFERENCES business.trip(id) ON DELETE CASCADE,
    idempotency_key UUID NOT NULL,
    task_type VARCHAR(20) NOT NULL,
    status VARCHAR(30) NOT NULL,
    baseline_trip_version INTEGER NOT NULL,
    trace_id UUID NOT NULL,
    retry_count INTEGER NOT NULL DEFAULT 0,
    error_code VARCHAR(80),
    error_message VARCHAR(500),
    version INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_planning_task_trip_idempotency UNIQUE (trip_id, idempotency_key),
    CONSTRAINT ck_planning_task_type CHECK (task_type IN ('CREATE', 'REPLAN')),
    CONSTRAINT ck_planning_task_status CHECK (
        status IN (
            'CREATED', 'QUEUED', 'RUNNING', 'WAITING_USER', 'RETRYING',
            'CANCELLING', 'CANCELLED', 'SUCCEEDED', 'FAILED'
        )
    ),
    CONSTRAINT ck_planning_task_baseline_version CHECK (baseline_trip_version >= 0),
    CONSTRAINT ck_planning_task_retry_count CHECK (retry_count >= 0),
    CONSTRAINT ck_planning_task_version CHECK (version >= 0)
);

CREATE INDEX idx_planning_task_trip_created
    ON business.planning_task(trip_id, created_at DESC);

CREATE UNIQUE INDEX uq_planning_task_one_active_per_trip
    ON business.planning_task(trip_id)
    WHERE status IN ('CREATED', 'QUEUED', 'RUNNING', 'WAITING_USER', 'RETRYING', 'CANCELLING');

CREATE TABLE business.outbox_event (
    id UUID PRIMARY KEY,
    aggregate_type VARCHAR(50) NOT NULL,
    aggregate_id UUID NOT NULL,
    event_type VARCHAR(80) NOT NULL,
    routing_key VARCHAR(100) NOT NULL,
    payload JSONB NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    retry_count INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_error VARCHAR(500),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sent_at TIMESTAMPTZ,
    CONSTRAINT ck_outbox_event_status CHECK (status IN ('PENDING', 'SENT')),
    CONSTRAINT ck_outbox_event_retry_count CHECK (retry_count >= 0)
);

CREATE INDEX idx_outbox_event_pending
    ON business.outbox_event(next_attempt_at, created_at)
    WHERE status = 'PENDING';
