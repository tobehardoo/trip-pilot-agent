-- V26: Allow transit leg estimated_cost to be NULL.
-- NULL means "cost could not be determined" (distinct from genuinely-free 0).
-- Existing rows with DEFAULT 0 are preserved — they represent legacy data
-- whose cost provenance is unknown (treated as UNKNOWN at the API level).

ALTER TABLE business.transit_leg
    ALTER COLUMN estimated_cost DROP NOT NULL,
    ALTER COLUMN estimated_cost DROP DEFAULT;
