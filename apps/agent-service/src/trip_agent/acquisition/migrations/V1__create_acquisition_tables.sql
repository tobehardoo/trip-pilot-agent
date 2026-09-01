CREATE SCHEMA IF NOT EXISTS agent;

CREATE TABLE IF NOT EXISTS agent.knowledge_resource (
    resource_id TEXT PRIMARY KEY CHECK (char_length(resource_id) = 64),
    source_id TEXT NOT NULL,
    city TEXT NOT NULL,
    source_url TEXT NOT NULL,
    final_url TEXT NOT NULL,
    etag TEXT,
    last_modified TEXT,
    current_content_hash TEXT CHECK (
        current_content_hash IS NULL OR char_length(current_content_hash) = 64
    ),
    last_attempted_at TIMESTAMPTZ NOT NULL,
    last_verified_at TIMESTAMPTZ,
    last_changed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (source_id, source_url)
);

CREATE TABLE IF NOT EXISTS agent.knowledge_snapshot (
    snapshot_id TEXT PRIMARY KEY CHECK (char_length(snapshot_id) = 64),
    resource_id TEXT NOT NULL REFERENCES agent.knowledge_resource (resource_id) ON DELETE RESTRICT,
    source_url TEXT NOT NULL,
    final_url TEXT NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL,
    published_at TIMESTAMPTZ,
    content_hash TEXT NOT NULL CHECK (char_length(content_hash) = 64),
    raw_content BYTEA NOT NULL,
    content_type TEXT,
    etag TEXT,
    last_modified TEXT,
    parser_version TEXT NOT NULL CHECK (char_length(parser_version) > 0),
    review_status TEXT NOT NULL DEFAULT 'PENDING' CHECK (review_status = 'PENDING'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (resource_id, content_hash, parser_version)
);

CREATE TABLE IF NOT EXISTS agent.knowledge_fetch_run (
    run_id TEXT PRIMARY KEY,
    resource_id TEXT NOT NULL REFERENCES agent.knowledge_resource (resource_id) ON DELETE RESTRICT,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('FETCHED', 'NOT_MODIFIED', 'FAILED')),
    attempt_count INTEGER NOT NULL CHECK (attempt_count > 0),
    attempts JSONB NOT NULL CHECK (jsonb_typeof(attempts) = 'array'),
    snapshot_id TEXT REFERENCES agent.knowledge_snapshot (snapshot_id) ON DELETE RESTRICT,
    error_code TEXT,
    error_message TEXT,
    retryable BOOLEAN,
    http_status INTEGER CHECK (http_status IS NULL OR http_status BETWEEN 100 AND 599),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (completed_at >= started_at),
    CHECK (jsonb_array_length(attempts) = attempt_count),
    CHECK (
        (status = 'FETCHED' AND snapshot_id IS NOT NULL)
        OR (status IN ('NOT_MODIFIED', 'FAILED') AND snapshot_id IS NULL)
    ),
    CHECK (
        (status = 'FAILED' AND error_code IS NOT NULL AND error_message IS NOT NULL
            AND retryable IS NOT NULL)
        OR (status <> 'FAILED' AND error_code IS NULL AND error_message IS NULL
            AND retryable IS NULL AND http_status IS NULL)
    )
);

CREATE INDEX IF NOT EXISTS knowledge_resource_source_idx
    ON agent.knowledge_resource (source_id, last_verified_at);

CREATE INDEX IF NOT EXISTS knowledge_snapshot_resource_idx
    ON agent.knowledge_snapshot (resource_id, fetched_at DESC);

CREATE INDEX IF NOT EXISTS knowledge_fetch_run_resource_idx
    ON agent.knowledge_fetch_run (resource_id, completed_at DESC);
