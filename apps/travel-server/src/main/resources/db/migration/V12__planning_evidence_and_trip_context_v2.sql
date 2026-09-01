ALTER TABLE business.trip_constraint
    ADD COLUMN arrival JSONB,
    ADD COLUMN departure JSONB,
    ADD COLUMN accommodation JSONB,
    ADD COLUMN must_visit_places JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN avoid_places JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN meal_windows JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN mobility_level VARCHAR(20) NOT NULL DEFAULT 'STANDARD',
    ADD CONSTRAINT ck_trip_constraint_mobility
        CHECK (mobility_level IN ('STANDARD', 'REDUCED', 'STEP_FREE'));

UPDATE business.trip_constraint
SET schema_version = 2;

ALTER TABLE business.guide_import
    ADD COLUMN enabled BOOLEAN NOT NULL DEFAULT TRUE;

CREATE INDEX guide_import_planning_evidence_idx
    ON business.guide_import(trip_id, enabled, fetched_at DESC);

CREATE INDEX guide_fact_freshness_idx
    ON business.guide_fact(guide_import_id, expires_at);
