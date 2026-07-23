CREATE TABLE business.itinerary_version_knowledge (
    itinerary_version_id UUID PRIMARY KEY
        REFERENCES business.itinerary_version(id) ON DELETE CASCADE,
    status VARCHAR(20) NOT NULL,
    query VARCHAR(200) NOT NULL,
    freshness_status VARCHAR(20) NOT NULL,
    freshness_checked_at TIMESTAMPTZ,
    stale_reason VARCHAR(60),
    message VARCHAR(300),
    CONSTRAINT ck_itinerary_knowledge_status
        CHECK (status IN ('REAL', 'DEMO', 'UNAVAILABLE')),
    CONSTRAINT ck_itinerary_knowledge_freshness
        CHECK (freshness_status IN ('FRESH', 'STALE', 'UNAVAILABLE')),
    CONSTRAINT ck_itinerary_knowledge_state CHECK (
        (status = 'REAL' AND freshness_status IN ('FRESH', 'STALE')
            AND freshness_checked_at IS NOT NULL AND message IS NULL)
        OR
        (status IN ('DEMO', 'UNAVAILABLE') AND freshness_status = 'UNAVAILABLE'
            AND freshness_checked_at IS NULL AND stale_reason IS NULL AND message IS NOT NULL)
    ),
    CONSTRAINT ck_itinerary_knowledge_fresh_reason CHECK (
        freshness_status <> 'FRESH' OR stale_reason IS NULL
    )
);

CREATE TABLE business.itinerary_knowledge_citation (
    id UUID PRIMARY KEY,
    itinerary_version_id UUID NOT NULL
        REFERENCES business.itinerary_version_knowledge(itinerary_version_id) ON DELETE CASCADE,
    citation_order INTEGER NOT NULL CHECK (citation_order >= 0),
    document_id VARCHAR(200) NOT NULL,
    document_version INTEGER NOT NULL CHECK (document_version >= 1),
    chunk_id VARCHAR(200) NOT NULL,
    chunk_index INTEGER NOT NULL CHECK (chunk_index >= 0),
    title VARCHAR(200) NOT NULL,
    source_url VARCHAR(2048) NOT NULL,
    source_name VARCHAR(120) NOT NULL,
    collected_at TIMESTAMPTZ NOT NULL,
    reliability_level VARCHAR(60) NOT NULL,
    similarity DOUBLE PRECISION NOT NULL CHECK (similarity >= -1 AND similarity <= 1),
    CONSTRAINT uq_itinerary_citation_order UNIQUE (itinerary_version_id, citation_order),
    CONSTRAINT uq_itinerary_citation_chunk UNIQUE (itinerary_version_id, chunk_id)
);

CREATE INDEX idx_itinerary_citation_version
    ON business.itinerary_knowledge_citation(itinerary_version_id, citation_order);
