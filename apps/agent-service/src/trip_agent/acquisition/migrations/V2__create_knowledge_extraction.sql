CREATE TABLE IF NOT EXISTS agent.knowledge_extraction (
    extraction_id TEXT PRIMARY KEY CHECK (char_length(extraction_id) = 64),
    snapshot_id TEXT NOT NULL REFERENCES agent.knowledge_snapshot (snapshot_id) ON DELETE RESTRICT,
    parser_version TEXT NOT NULL CHECK (char_length(parser_version) > 0),
    status TEXT NOT NULL CHECK (status IN ('EXTRACTED', 'REJECTED')),
    title TEXT,
    content TEXT,
    content_hash TEXT CHECK (content_hash IS NULL OR char_length(content_hash) = 64),
    published_at TIMESTAMPTZ,
    content_source TEXT,
    quality_issues JSONB NOT NULL CHECK (jsonb_typeof(quality_issues) = 'array'),
    result_fingerprint TEXT NOT NULL CHECK (char_length(result_fingerprint) = 64),
    extracted_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (snapshot_id, parser_version),
    CHECK (
        (status = 'EXTRACTED' AND title IS NOT NULL AND content IS NOT NULL
            AND content_hash IS NOT NULL)
        OR (status = 'REJECTED' AND title IS NULL AND content IS NULL
            AND content_hash IS NULL AND published_at IS NULL AND content_source IS NULL)
    ),
    CHECK (
        (status = 'EXTRACTED'
            AND NOT jsonb_path_exists(quality_issues, '$[*] ? (@.severity == "ERROR")'))
        OR (status = 'REJECTED'
            AND jsonb_path_exists(quality_issues, '$[*] ? (@.severity == "ERROR")'))
    )
);

CREATE INDEX IF NOT EXISTS knowledge_extraction_snapshot_idx
    ON agent.knowledge_extraction (snapshot_id, parser_version);
