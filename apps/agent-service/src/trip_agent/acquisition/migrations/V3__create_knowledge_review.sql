ALTER TABLE agent.knowledge_resource
    ADD COLUMN source_name TEXT,
    ADD COLUMN reliability_level TEXT
        CHECK (reliability_level IN ('OFFICIAL', 'CURATED', 'COMMUNITY'));

ALTER TABLE agent.knowledge_snapshot
    DROP CONSTRAINT knowledge_snapshot_review_status_check,
    ADD CONSTRAINT knowledge_snapshot_review_status_check
        CHECK (review_status IN ('PENDING', 'APPROVED', 'REJECTED', 'WITHDRAWN'));

CREATE TABLE agent.knowledge_review_action (
    action_id TEXT PRIMARY KEY CHECK (char_length(action_id) = 64),
    snapshot_id TEXT NOT NULL
        REFERENCES agent.knowledge_snapshot (snapshot_id) ON DELETE RESTRICT,
    extraction_id TEXT
        REFERENCES agent.knowledge_extraction (extraction_id) ON DELETE RESTRICT,
    action TEXT NOT NULL CHECK (action IN ('APPROVE', 'REJECT', 'WITHDRAW')),
    parent_action_id TEXT
        REFERENCES agent.knowledge_review_action (action_id) ON DELETE RESTRICT,
    reviewer_id TEXT NOT NULL CHECK (
        char_length(btrim(reviewer_id)) BETWEEN 1 AND 200
    ),
    note TEXT NOT NULL CHECK (char_length(btrim(note)) BETWEEN 1 AND 2000),
    reviewed_at TIMESTAMPTZ NOT NULL,
    decision_fingerprint TEXT NOT NULL CHECK (char_length(decision_fingerprint) = 64),
    category TEXT CHECK (
        category IS NULL OR category IN (
            'accommodation', 'culture', 'food', 'poi', 'season', 'theme', 'travel_tip'
        )
    ),
    valid_from DATE,
    valid_to DATE,
    applicable_seasons TEXT[] NOT NULL DEFAULT '{}',
    traveler_types TEXT[] NOT NULL DEFAULT '{}',
    document_id TEXT,
    document_version INTEGER,
    document_city TEXT,
    document_source_name TEXT,
    document_reliability_level TEXT CHECK (
        document_reliability_level IS NULL
        OR document_reliability_level IN ('OFFICIAL', 'CURATED', 'COMMUNITY')
    ),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (valid_from IS NULL OR valid_to IS NULL OR valid_from <= valid_to),
    CHECK (applicable_seasons <@ ARRAY['all', 'spring', 'summer', 'autumn', 'winter']),
    CHECK (
        traveler_types <@ ARRAY['SOLO', 'COUPLE', 'FAMILY', 'FRIENDS', 'BUSINESS']
    ),
    CHECK (
        (action = 'APPROVE'
            AND extraction_id IS NOT NULL
            AND parent_action_id IS NULL
            AND category IS NOT NULL
            AND document_id IS NOT NULL
            AND document_version > 0
            AND document_city IS NOT NULL
            AND document_source_name IS NOT NULL
            AND document_reliability_level IS NOT NULL)
        OR (action = 'REJECT'
            AND extraction_id IS NOT NULL
            AND parent_action_id IS NULL
            AND category IS NULL
            AND valid_from IS NULL
            AND valid_to IS NULL
            AND applicable_seasons = '{}'
            AND traveler_types = '{}'
            AND document_id IS NULL
            AND document_version IS NULL
            AND document_city IS NULL
            AND document_source_name IS NULL
            AND document_reliability_level IS NULL)
        OR (action = 'WITHDRAW'
            AND extraction_id IS NULL
            AND parent_action_id IS NOT NULL
            AND category IS NULL
            AND valid_from IS NULL
            AND valid_to IS NULL
            AND applicable_seasons = '{}'
            AND traveler_types = '{}'
            AND document_id IS NULL
            AND document_version IS NULL
            AND document_city IS NULL
            AND document_source_name IS NULL
            AND document_reliability_level IS NULL)
    )
);

CREATE UNIQUE INDEX knowledge_review_initial_snapshot_idx
    ON agent.knowledge_review_action (snapshot_id)
    WHERE action IN ('APPROVE', 'REJECT');

CREATE UNIQUE INDEX knowledge_review_withdraw_parent_idx
    ON agent.knowledge_review_action (parent_action_id)
    WHERE action = 'WITHDRAW';

CREATE UNIQUE INDEX knowledge_review_document_version_idx
    ON agent.knowledge_review_action (document_id, document_version)
    WHERE action = 'APPROVE';

CREATE TABLE agent.knowledge_publication (
    review_action_id TEXT PRIMARY KEY
        REFERENCES agent.knowledge_review_action (action_id) ON DELETE RESTRICT,
    status TEXT NOT NULL CHECK (
        status IN ('PENDING', 'PUBLISHING', 'PUBLISHED', 'FAILED', 'CANCELLED')
    ),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    claim_started_at TIMESTAMPTZ,
    published_at TIMESTAMPTZ,
    failed_at TIMESTAMPTZ,
    last_error TEXT,
    chunk_count INTEGER CHECK (chunk_count IS NULL OR chunk_count >= 0),
    importer_status TEXT CHECK (
        importer_status IS NULL OR importer_status IN ('created', 'embedded', 'unchanged')
    ),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (
        (status = 'PENDING'
            AND attempt_count = 0
            AND claim_started_at IS NULL
            AND published_at IS NULL
            AND failed_at IS NULL
            AND last_error IS NULL
            AND chunk_count IS NULL
            AND importer_status IS NULL)
        OR (status = 'PUBLISHING'
            AND attempt_count > 0
            AND claim_started_at IS NOT NULL
            AND published_at IS NULL
            AND failed_at IS NULL
            AND last_error IS NULL
            AND chunk_count IS NULL
            AND importer_status IS NULL)
        OR (status = 'FAILED'
            AND attempt_count > 0
            AND claim_started_at IS NULL
            AND published_at IS NULL
            AND failed_at IS NOT NULL
            AND last_error IS NOT NULL
            AND chunk_count IS NULL
            AND importer_status IS NULL)
        OR (status = 'PUBLISHED'
            AND attempt_count > 0
            AND claim_started_at IS NULL
            AND published_at IS NOT NULL
            AND failed_at IS NULL
            AND last_error IS NULL
            AND chunk_count IS NOT NULL
            AND importer_status IS NOT NULL)
        OR (status = 'CANCELLED'
            AND claim_started_at IS NULL
            AND published_at IS NULL
            AND failed_at IS NULL
            AND last_error IS NULL
            AND chunk_count IS NULL
            AND importer_status IS NULL)
    )
);

CREATE INDEX knowledge_publication_status_idx
    ON agent.knowledge_publication (status, updated_at);
