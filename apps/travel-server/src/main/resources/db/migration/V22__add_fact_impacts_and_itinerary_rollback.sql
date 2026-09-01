ALTER TABLE business.itinerary_version
    DROP CONSTRAINT ck_itinerary_version_source;

ALTER TABLE business.itinerary_version
    ADD CONSTRAINT ck_itinerary_version_source
        CHECK (version_source IN (
            'PLANNING_TASK', 'USER_EDIT', 'LOCAL_REPLAN', 'ROLLBACK'
        )),
    ADD COLUMN rollback_from_version_id UUID,
    ADD CONSTRAINT fk_itinerary_version_rollback_source
        FOREIGN KEY (itinerary_id, rollback_from_version_id)
        REFERENCES business.itinerary_version(itinerary_id, id);

CREATE TABLE business.planning_fact_impact (
    id UUID PRIMARY KEY,
    itinerary_version_id UUID NOT NULL
        REFERENCES business.itinerary_version(id) ON DELETE CASCADE,
    planning_task_id UUID NOT NULL
        REFERENCES business.planning_task(id) ON DELETE CASCADE,
    fact_id VARCHAR(80) NOT NULL,
    category VARCHAR(60) NOT NULL,
    applicable_date DATE,
    effect VARCHAR(60) NOT NULL,
    target_poi_id VARCHAR(100),
    target_name VARCHAR(120),
    reason VARCHAR(300) NOT NULL,
    source_name VARCHAR(120) NOT NULL,
    source_type VARCHAR(60) NOT NULL,
    source_url VARCHAR(2048),
    reliability_level VARCHAR(60) NOT NULL,
    checked_at TIMESTAMPTZ NOT NULL,
    evidence VARCHAR(2000) NOT NULL,
    stale BOOLEAN NOT NULL,
    conflicted BOOLEAN NOT NULL,
    refresh_failed BOOLEAN NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX planning_fact_impact_version_idx
    ON business.planning_fact_impact(itinerary_version_id, applicable_date, id);
CREATE INDEX planning_fact_impact_task_idx
    ON business.planning_fact_impact(planning_task_id);

CREATE TABLE business.itinerary_rollback (
    id UUID PRIMARY KEY,
    itinerary_id UUID NOT NULL
        REFERENCES business.itinerary(id) ON DELETE CASCADE,
    source_version_id UUID NOT NULL
        REFERENCES business.itinerary_version(id) ON DELETE RESTRICT,
    result_version_id UUID NOT NULL UNIQUE
        REFERENCES business.itinerary_version(id) ON DELETE RESTRICT,
    owner_id UUID NOT NULL
        REFERENCES business.user_account(id) ON DELETE RESTRICT,
    idempotency_key UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT itinerary_rollback_idempotency_unique
        UNIQUE (itinerary_id, idempotency_key)
);

CREATE INDEX itinerary_rollback_source_idx
    ON business.itinerary_rollback(itinerary_id, source_version_id, created_at DESC);
