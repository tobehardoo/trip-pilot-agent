ALTER TABLE business.activity
    ADD CONSTRAINT uq_activity_day_identity UNIQUE (itinerary_day_id, id);

CREATE TABLE business.transit_leg (
    id UUID PRIMARY KEY,
    itinerary_day_id UUID NOT NULL REFERENCES business.itinerary_day(id) ON DELETE CASCADE,
    leg_order INTEGER NOT NULL,
    from_activity_id UUID NOT NULL,
    to_activity_id UUID NOT NULL,
    mode VARCHAR(20) NOT NULL,
    distance_meters INTEGER NOT NULL,
    duration_seconds INTEGER NOT NULL,
    provider VARCHAR(30) NOT NULL,
    estimated BOOLEAN NOT NULL,
    polyline JSONB NOT NULL,
    CONSTRAINT uq_transit_leg_order UNIQUE (itinerary_day_id, leg_order),
    CONSTRAINT fk_transit_leg_origin FOREIGN KEY (itinerary_day_id, from_activity_id)
        REFERENCES business.activity(itinerary_day_id, id) ON DELETE CASCADE,
    CONSTRAINT fk_transit_leg_destination FOREIGN KEY (itinerary_day_id, to_activity_id)
        REFERENCES business.activity(itinerary_day_id, id) ON DELETE CASCADE,
    CONSTRAINT ck_transit_leg_order CHECK (leg_order >= 0),
    CONSTRAINT ck_transit_leg_distinct_activities CHECK (from_activity_id <> to_activity_id),
    CONSTRAINT ck_transit_leg_mode CHECK (mode = 'WALKING'),
    CONSTRAINT ck_transit_leg_distance CHECK (
        distance_meters BETWEEN 0 AND 40100000
    ),
    CONSTRAINT ck_transit_leg_duration CHECK (
        duration_seconds BETWEEN 0 AND 31536000
    ),
    CONSTRAINT ck_transit_leg_provider_estimate CHECK (
        (provider = 'AMAP' AND estimated = FALSE)
        OR (provider = 'DEMO' AND estimated = TRUE)
    ),
    CONSTRAINT ck_transit_leg_polyline CHECK (
        jsonb_typeof(polyline) = 'array'
        AND jsonb_array_length(polyline) BETWEEN 1 AND 5000
    )
);
