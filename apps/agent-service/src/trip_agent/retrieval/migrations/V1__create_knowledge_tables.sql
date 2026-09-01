CREATE SCHEMA IF NOT EXISTS agent;

CREATE TABLE IF NOT EXISTS agent.knowledge_document (
    document_id TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version > 0),
    city TEXT NOT NULL,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    content_hash CHAR(64) NOT NULL,
    version_fingerprint CHAR(64) NOT NULL,
    source_url TEXT NOT NULL,
    source_name TEXT NOT NULL,
    published_at DATE,
    collected_at TIMESTAMPTZ NOT NULL,
    valid_from DATE,
    valid_to DATE,
    applicable_seasons TEXT[] NOT NULL DEFAULT '{}',
    traveler_types TEXT[] NOT NULL DEFAULT '{}',
    reliability_level TEXT NOT NULL,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (document_id, version),
    CHECK (valid_from IS NULL OR valid_to IS NULL OR valid_from <= valid_to)
);

CREATE TABLE IF NOT EXISTS agent.knowledge_chunk (
    chunk_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    document_version INTEGER NOT NULL,
    chunk_index INTEGER NOT NULL CHECK (chunk_index >= 0),
    heading_path TEXT[] NOT NULL DEFAULT '{}',
    chunk_content TEXT NOT NULL,
    content_hash CHAR(64) NOT NULL,
    token_count INTEGER NOT NULL CHECK (token_count > 0),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (document_id, document_version, chunk_index),
    FOREIGN KEY (document_id, document_version)
        REFERENCES agent.knowledge_document (document_id, version)
        ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS agent.knowledge_chunk_embedding (
    chunk_id TEXT NOT NULL REFERENCES agent.knowledge_chunk (chunk_id) ON DELETE CASCADE,
    embedding_model TEXT NOT NULL,
    embedding_dimensions INTEGER NOT NULL CHECK (embedding_dimensions > 0),
    embedding VECTOR NOT NULL,
    embedded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (chunk_id, embedding_model, embedding_dimensions)
);

CREATE INDEX IF NOT EXISTS knowledge_document_city_category_idx
    ON agent.knowledge_document (city, category);

CREATE INDEX IF NOT EXISTS knowledge_chunk_document_idx
    ON agent.knowledge_chunk (document_id, document_version, chunk_index);

CREATE INDEX IF NOT EXISTS knowledge_chunk_embedding_model_idx
    ON agent.knowledge_chunk_embedding (embedding_model, embedding_dimensions, chunk_id);
