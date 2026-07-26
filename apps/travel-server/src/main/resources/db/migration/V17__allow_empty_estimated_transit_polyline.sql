ALTER TABLE business.transit_leg
    DROP CONSTRAINT ck_transit_leg_polyline;

ALTER TABLE business.transit_leg
    ADD CONSTRAINT ck_transit_leg_polyline CHECK (
        jsonb_typeof(polyline) = 'array'
        AND jsonb_array_length(polyline) BETWEEN 0 AND 5000
        AND (
            estimated = TRUE
            OR jsonb_array_length(polyline) >= 1
        )
    );
