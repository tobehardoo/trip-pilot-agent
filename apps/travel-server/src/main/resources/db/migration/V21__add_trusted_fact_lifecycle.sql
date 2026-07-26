CREATE TABLE business.normalized_document (
    guide_import_id UUID NOT NULL
        REFERENCES business.guide_import(id) ON DELETE CASCADE,
    document_id VARCHAR(40) NOT NULL,
    source_type VARCHAR(60) NOT NULL,
    source_name VARCHAR(300) NOT NULL,
    source_url VARCHAR(2048),
    city VARCHAR(120) NOT NULL,
    title VARCHAR(300) NOT NULL,
    content TEXT NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL,
    content_hash CHAR(64) NOT NULL,
    encoding VARCHAR(80) NOT NULL,
    language VARCHAR(40) NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    reliability_level VARCHAR(40) NOT NULL,
    source_reviewed BOOLEAN NOT NULL DEFAULT FALSE,
    model_status VARCHAR(20) NOT NULL DEFAULT 'SKIPPED',
    model_attempts INTEGER NOT NULL DEFAULT 0,
    model_failure_code VARCHAR(80),
    model_failure_reason VARCHAR(1000),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guide_import_id, document_id),
    CONSTRAINT normalized_document_content_length_check
        CHECK (length(content) BETWEEN 1 AND 100000),
    CONSTRAINT normalized_document_hash_check
        CHECK (content_hash ~ '^[a-f0-9]{64}$'),
    CONSTRAINT normalized_document_model_status_check
        CHECK (model_status IN ('EXTRACTED', 'SKIPPED', 'FAILED')),
    CONSTRAINT normalized_document_model_attempts_check CHECK (model_attempts >= 0)
);

CREATE TABLE business.trusted_fact (
    guide_import_id UUID NOT NULL
        REFERENCES business.guide_import(id) ON DELETE CASCADE,
    fact_id VARCHAR(40) NOT NULL,
    document_id VARCHAR(40) NOT NULL,
    city VARCHAR(120) NOT NULL,
    category VARCHAR(60) NOT NULL,
    statement VARCHAR(2000) NOT NULL,
    normalized_value JSONB NOT NULL,
    evidence VARCHAR(2000) NOT NULL,
    evidence_start INTEGER NOT NULL,
    evidence_end INTEGER NOT NULL,
    confidence NUMERIC(4, 3) NOT NULL,
    effective_date DATE,
    checked_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    source_type VARCHAR(60) NOT NULL,
    source_name VARCHAR(300) NOT NULL,
    source_url VARCHAR(2048),
    reliability_level VARCHAR(40) NOT NULL,
    source_reviewed BOOLEAN NOT NULL,
    hard_constraint_eligible BOOLEAN NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guide_import_id, fact_id),
    FOREIGN KEY (guide_import_id, document_id)
        REFERENCES business.normalized_document(guide_import_id, document_id)
        ON DELETE CASCADE,
    CONSTRAINT trusted_fact_evidence_span_check
        CHECK (evidence_start >= 0 AND evidence_end > evidence_start),
    CONSTRAINT trusted_fact_confidence_check
        CHECK (confidence BETWEEN 0 AND 1),
    CONSTRAINT trusted_fact_expiry_check
        CHECK (expires_at > checked_at)
);

CREATE INDEX trusted_fact_source_idx
    ON business.trusted_fact(guide_import_id, document_id, source_type);
CREATE INDEX trusted_fact_lifecycle_idx
    ON business.trusted_fact(active, expires_at, checked_at DESC);
CREATE INDEX trusted_fact_city_category_date_idx
    ON business.trusted_fact(city, category, effective_date, expires_at);

CREATE TABLE business.fact_validation_rejection (
    id UUID PRIMARY KEY,
    guide_import_id UUID NOT NULL
        REFERENCES business.guide_import(id) ON DELETE CASCADE,
    category VARCHAR(60) NOT NULL,
    statement VARCHAR(2000) NOT NULL,
    reasons JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX fact_validation_rejection_import_idx
    ON business.fact_validation_rejection(guide_import_id, created_at);

CREATE TABLE business.fact_merge_decision (
    id UUID PRIMARY KEY,
    guide_import_id UUID NOT NULL
        REFERENCES business.guide_import(id) ON DELETE CASCADE,
    selected_fact_id VARCHAR(40) NOT NULL,
    conflict_fact_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    downgraded_fact_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    decision_reason VARCHAR(1000) NOT NULL,
    needs_manual_review BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX fact_merge_decision_import_idx
    ON business.fact_merge_decision(guide_import_id, created_at);

CREATE TABLE business.city_intelligence_refresh (
    id UUID PRIMARY KEY,
    trip_id UUID NOT NULL REFERENCES business.trip(id) ON DELETE CASCADE,
    city_code VARCHAR(32) NOT NULL,
    idempotency_key UUID NOT NULL,
    status VARCHAR(30) NOT NULL,
    requested_categories JSONB NOT NULL DEFAULT '[]'::jsonb,
    provider_diagnostics JSONB NOT NULL DEFAULT '[]'::jsonb,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    error_code VARCHAR(80),
    error_message VARCHAR(500),
    version INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT city_intelligence_refresh_status_check CHECK (
        status IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'PARTIAL', 'FAILED')
    ),
    CONSTRAINT city_intelligence_refresh_attempt_check CHECK (attempt_count >= 0),
    CONSTRAINT city_intelligence_refresh_version_check CHECK (version >= 0)
);

CREATE UNIQUE INDEX city_intelligence_refresh_idempotency_idx
    ON business.city_intelligence_refresh(trip_id, idempotency_key);
CREATE UNIQUE INDEX city_intelligence_refresh_one_running_idx
    ON business.city_intelligence_refresh(trip_id)
    WHERE status IN ('QUEUED', 'RUNNING');

CREATE TABLE business.city_intelligence_snapshot (
    id UUID PRIMARY KEY,
    trip_id UUID NOT NULL REFERENCES business.trip(id) ON DELETE CASCADE,
    refresh_id UUID NOT NULL
        REFERENCES business.city_intelligence_refresh(id) ON DELETE RESTRICT,
    city_code VARCHAR(32) NOT NULL,
    travel_start_date DATE NOT NULL,
    travel_end_date DATE NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1,
    generated_at TIMESTAMPTZ NOT NULL,
    stale BOOLEAN NOT NULL DEFAULT FALSE,
    sources JSONB NOT NULL DEFAULT '[]'::jsonb,
    facts JSONB NOT NULL DEFAULT '[]'::jsonb,
    conflicts JSONB NOT NULL DEFAULT '[]'::jsonb,
    excluded_facts JSONB NOT NULL DEFAULT '[]'::jsonb,
    provider_diagnostics JSONB NOT NULL DEFAULT '[]'::jsonb,
    content_digest CHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT city_intelligence_snapshot_dates_check
        CHECK (travel_end_date >= travel_start_date),
    CONSTRAINT city_intelligence_snapshot_schema_check CHECK (schema_version >= 1),
    CONSTRAINT city_intelligence_snapshot_digest_check
        CHECK (content_digest ~ '^[a-f0-9]{64}$')
);

CREATE INDEX city_intelligence_snapshot_trip_generated_idx
    ON business.city_intelligence_snapshot(trip_id, generated_at DESC);

CREATE TABLE business.planning_context_snapshot (
    id UUID PRIMARY KEY,
    trip_id UUID NOT NULL REFERENCES business.trip(id) ON DELETE CASCADE,
    planning_task_id UUID NOT NULL
        REFERENCES business.planning_task(id) ON DELETE CASCADE,
    city_intelligence_snapshot_id UUID
        REFERENCES business.city_intelligence_snapshot(id) ON DELETE RESTRICT,
    schema_version INTEGER NOT NULL DEFAULT 3,
    city VARCHAR(120) NOT NULL,
    travel_start_date DATE NOT NULL,
    travel_end_date DATE NOT NULL,
    generated_at TIMESTAMPTZ NOT NULL,
    stale BOOLEAN NOT NULL DEFAULT FALSE,
    sources JSONB NOT NULL DEFAULT '[]'::jsonb,
    facts JSONB NOT NULL DEFAULT '[]'::jsonb,
    conflicts JSONB NOT NULL DEFAULT '[]'::jsonb,
    excluded_facts JSONB NOT NULL DEFAULT '[]'::jsonb,
    diagnostics JSONB NOT NULL DEFAULT '[]'::jsonb,
    content_digest CHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT planning_context_snapshot_dates_check
        CHECK (travel_end_date >= travel_start_date),
    CONSTRAINT planning_context_snapshot_schema_check CHECK (schema_version >= 1),
    CONSTRAINT planning_context_snapshot_digest_check
        CHECK (content_digest ~ '^[a-f0-9]{64}$')
);

CREATE UNIQUE INDEX planning_context_snapshot_task_unique_idx
    ON business.planning_context_snapshot(planning_task_id);
CREATE INDEX planning_context_snapshot_trip_created_idx
    ON business.planning_context_snapshot(trip_id, created_at DESC);
