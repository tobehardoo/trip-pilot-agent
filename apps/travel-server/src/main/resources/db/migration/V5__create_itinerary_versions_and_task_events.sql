ALTER TABLE business.planning_task
    ADD COLUMN constraint_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb;

UPDATE business.planning_task AS task
SET constraint_snapshot = outbox.payload #> '{payload,trip,constraints}'
FROM business.outbox_event AS outbox
WHERE outbox.aggregate_id = task.id
  AND outbox.event_type = 'PLANNING_CREATE_REQUESTED';

ALTER TABLE business.planning_task
    ALTER COLUMN constraint_snapshot DROP DEFAULT;

CREATE TABLE business.planning_task_event (
    id BIGSERIAL PRIMARY KEY,
    event_id UUID NOT NULL UNIQUE,
    task_id UUID NOT NULL REFERENCES business.planning_task(id) ON DELETE CASCADE,
    event_type VARCHAR(80) NOT NULL,
    schema_version INTEGER NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_planning_task_event_schema_version CHECK (schema_version > 0)
);

CREATE INDEX idx_planning_task_event_task_id
    ON business.planning_task_event(task_id, id);

INSERT INTO business.planning_task_event(
    event_id, task_id, event_type, schema_version, payload, created_at
)
SELECT id, id, 'PLANNING_QUEUED', 1, jsonb_build_object('status', status), created_at
FROM business.planning_task
WHERE status = 'QUEUED';

CREATE TABLE business.itinerary (
    id UUID PRIMARY KEY,
    trip_id UUID NOT NULL UNIQUE REFERENCES business.trip(id) ON DELETE CASCADE,
    current_version_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE business.itinerary_version (
    id UUID PRIMARY KEY,
    itinerary_id UUID NOT NULL REFERENCES business.itinerary(id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL,
    parent_version_id UUID,
    planning_task_id UUID NOT NULL UNIQUE REFERENCES business.planning_task(id),
    title VARCHAR(200) NOT NULL,
    estimated_total_cost NUMERIC(12, 2) NOT NULL,
    provider VARCHAR(30) NOT NULL,
    constraint_snapshot JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_itinerary_version_number UNIQUE (itinerary_id, version_number),
    CONSTRAINT uq_itinerary_version_identity UNIQUE (itinerary_id, id),
    CONSTRAINT ck_itinerary_version_number CHECK (version_number > 0),
    CONSTRAINT ck_itinerary_version_cost CHECK (estimated_total_cost >= 0),
    CONSTRAINT fk_itinerary_version_parent FOREIGN KEY (itinerary_id, parent_version_id)
        REFERENCES business.itinerary_version(itinerary_id, id)
);

ALTER TABLE business.itinerary
    ADD CONSTRAINT fk_itinerary_current_version
    FOREIGN KEY (id, current_version_id)
    REFERENCES business.itinerary_version(itinerary_id, id);

CREATE TABLE business.itinerary_day (
    id UUID PRIMARY KEY,
    itinerary_version_id UUID NOT NULL
        REFERENCES business.itinerary_version(id) ON DELETE CASCADE,
    day_date DATE NOT NULL,
    day_index INTEGER NOT NULL,
    CONSTRAINT uq_itinerary_day_index UNIQUE (itinerary_version_id, day_index),
    CONSTRAINT uq_itinerary_day_date UNIQUE (itinerary_version_id, day_date),
    CONSTRAINT ck_itinerary_day_index CHECK (day_index >= 0)
);

CREATE TABLE business.activity (
    id UUID PRIMARY KEY,
    itinerary_day_id UUID NOT NULL REFERENCES business.itinerary_day(id) ON DELETE CASCADE,
    activity_order INTEGER NOT NULL,
    title VARCHAR(200) NOT NULL,
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ NOT NULL,
    estimated_cost NUMERIC(12, 2) NOT NULL,
    source VARCHAR(30) NOT NULL,
    CONSTRAINT uq_activity_order UNIQUE (itinerary_day_id, activity_order),
    CONSTRAINT ck_activity_order CHECK (activity_order >= 0),
    CONSTRAINT ck_activity_time CHECK (end_time > start_time),
    CONSTRAINT ck_activity_cost CHECK (estimated_cost >= 0)
);
