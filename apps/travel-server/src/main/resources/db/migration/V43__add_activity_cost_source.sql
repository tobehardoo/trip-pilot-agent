-- B1: surface per-activity cost source (PROVIDER / RULE_ESTIMATE /
-- CATEGORY_ESTIMATE / CITY_ESTIMATE / DEMO / UNKNOWN) from the planning
-- wire through to the API.  NULL rows (e.g. activities persisted before
-- this migration) are presented to consumers as UNKNOWN.
ALTER TABLE business.activity
    ADD COLUMN cost_source VARCHAR(32) NULL;