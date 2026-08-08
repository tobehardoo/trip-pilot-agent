ALTER TABLE business.trip
    ADD COLUMN region_ref JSONB;

ALTER TABLE business.trip
    ADD CONSTRAINT ck_trip_region_ref_object
    CHECK (region_ref IS NULL OR jsonb_typeof(region_ref) = 'object');
