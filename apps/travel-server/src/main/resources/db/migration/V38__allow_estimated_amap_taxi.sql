-- B19-D: a TAXI leg combines real AMAP road geometry with a locally
-- estimated fare and wait time.  Keep the existing provider/estimate
-- coupling intact for every other mode and require real geometry for the
-- narrowly added mixed-provenance state.

ALTER TABLE business.transit_leg
    DROP CONSTRAINT ck_transit_leg_provider_estimate;

ALTER TABLE business.transit_leg
    ADD CONSTRAINT ck_transit_leg_provider_estimate CHECK (
        (provider = 'AMAP' AND estimated = FALSE)
        OR (provider = 'DEMO' AND estimated = TRUE)
        OR (
            mode = 'TAXI'
            AND provider = 'AMAP'
            AND estimated = TRUE
            AND jsonb_typeof(polyline) = 'array'
            AND jsonb_array_length(polyline) BETWEEN 1 AND 5000
        )
    );
