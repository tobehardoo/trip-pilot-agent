CREATE TABLE business.guide_import (
    id UUID PRIMARY KEY,
    trip_id UUID NOT NULL REFERENCES business.trip(id) ON DELETE CASCADE,
    source_url TEXT NOT NULL,
    final_url TEXT NOT NULL,
    source_host TEXT NOT NULL,
    title VARCHAR(300) NOT NULL,
    excerpt TEXT NOT NULL,
    content_hash CHAR(64) NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (trip_id, final_url, content_hash)
);

CREATE TABLE business.guide_fact (
    id UUID PRIMARY KEY,
    guide_import_id UUID NOT NULL REFERENCES business.guide_import(id) ON DELETE CASCADE,
    category VARCHAR(30) NOT NULL CHECK (
        category IN (
            'ATTRACTION', 'DINING', 'TRANSPORT', 'TIMING',
            'COST', 'QUEUE', 'RESERVATION', 'TIP'
        )
    ),
    statement TEXT NOT NULL,
    evidence TEXT NOT NULL,
    confidence DOUBLE PRECISION NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    observed_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (expires_at > observed_at)
);

CREATE INDEX guide_import_trip_idx
    ON business.guide_import(trip_id, fetched_at DESC);

CREATE INDEX guide_fact_import_idx
    ON business.guide_fact(guide_import_id, created_at, id);
