ALTER TABLE business.trip_constraint
    ADD COLUMN traveler_type VARCHAR(20) NOT NULL DEFAULT 'SOLO';

ALTER TABLE business.trip_constraint
    ALTER COLUMN traveler_type DROP DEFAULT,
    ADD CONSTRAINT ck_trip_constraint_traveler_type
        CHECK (traveler_type IN ('SOLO', 'COUPLE', 'FAMILY', 'FRIENDS', 'BUSINESS'));
