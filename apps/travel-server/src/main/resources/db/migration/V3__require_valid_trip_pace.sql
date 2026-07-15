LOCK TABLE business.trip_constraint IN ACCESS EXCLUSIVE MODE;

UPDATE business.trip_constraint
SET pace = 'BALANCED'
WHERE pace IS NULL;

ALTER TABLE business.trip_constraint
    ALTER COLUMN pace SET NOT NULL,
    ADD CONSTRAINT ck_trip_constraint_pace
        CHECK (pace IN ('RELAXED', 'BALANCED', 'INTENSIVE'));
