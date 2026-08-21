-- B19-E: carry the accommodation resolution status on each itinerary version
-- so edit / rollback / share / export can render the hotel state.
ALTER TABLE business.itinerary_version
    ADD COLUMN accommodation_status VARCHAR(32),
    ADD COLUMN accommodation_label VARCHAR(255);

-- UNRESOLVED / CONFIRMED / AREA_ESTIMATED only.
ALTER TABLE business.itinerary_version
    ADD CONSTRAINT ck_itinerary_version_accommodation_status
    CHECK (accommodation_status IS NULL OR accommodation_status IN (
        'CONFIRMED', 'AREA_ESTIMATED', 'UNRESOLVED'));
