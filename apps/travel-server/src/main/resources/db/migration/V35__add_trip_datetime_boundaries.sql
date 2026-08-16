ALTER TABLE business.trip
    ADD COLUMN arrival_at TIMESTAMPTZ,
    ADD COLUMN departure_at TIMESTAMPTZ;

ALTER TABLE business.trip
    ADD CONSTRAINT ck_trip_boundary_both_or_neither
    CHECK ((arrival_at IS NULL) = (departure_at IS NULL));

ALTER TABLE business.trip
    ADD CONSTRAINT ck_trip_boundary_order
    CHECK (arrival_at IS NULL OR arrival_at < departure_at);
