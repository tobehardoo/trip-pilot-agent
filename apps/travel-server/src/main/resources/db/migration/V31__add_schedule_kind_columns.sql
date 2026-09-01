-- V31: forward-compatible schedule-model columns (B3).
-- Additive columns only; no backfill, no destructive rewrite.
-- Existing rows keep NULL day_type/kind (== ATTRACTION / FULL_DAY semantics)
-- and time_fixed = FALSE.

ALTER TABLE business.itinerary_day
    ADD COLUMN IF NOT EXISTS day_type VARCHAR(20);

ALTER TABLE business.activity
    ADD COLUMN IF NOT EXISTS kind VARCHAR(20);

ALTER TABLE business.activity
    ADD COLUMN IF NOT EXISTS time_fixed BOOLEAN NOT NULL DEFAULT FALSE;

-- Relax ck_activity_provider_metadata so structural schedule nodes
-- (MEAL / ACCOMMODATION / ARRIVAL / DEPARTURE) may carry no provider
-- metadata when no real POI could be resolved. Non-structural activities
-- (kind NULL / ATTRACTION / EXPERIENCE) keep the strict AMAP metadata
-- requirement. This is a forward update: old rows (kind NULL) are unaffected.
ALTER TABLE business.activity
    DROP CONSTRAINT ck_activity_provider_metadata;

ALTER TABLE business.activity
    ADD CONSTRAINT ck_activity_provider_metadata CHECK (
        (
            source = 'DEMO'
            AND provider_poi_id IS NULL AND longitude IS NULL
            AND latitude IS NULL AND address IS NULL
        )
        OR (
            source = 'AMAP'
            AND kind IN ('MEAL', 'ACCOMMODATION', 'ARRIVAL', 'DEPARTURE')
            AND (
                (
                    provider_poi_id IS NULL AND longitude IS NULL
                    AND latitude IS NULL AND address IS NULL
                )
                OR (
                    provider_poi_id IS NOT NULL AND BTRIM(provider_poi_id) <> ''
                    AND longitude IS NOT NULL AND latitude IS NOT NULL
                    AND address IS NOT NULL AND BTRIM(address) <> ''
                )
            )
        )
        OR (
            source = 'AMAP'
            AND (kind IS NULL OR kind NOT IN ('MEAL', 'ACCOMMODATION', 'ARRIVAL', 'DEPARTURE'))
            AND provider_poi_id IS NOT NULL AND BTRIM(provider_poi_id) <> ''
            AND longitude IS NOT NULL AND latitude IS NOT NULL
            AND address IS NOT NULL AND BTRIM(address) <> ''
        )
    );
