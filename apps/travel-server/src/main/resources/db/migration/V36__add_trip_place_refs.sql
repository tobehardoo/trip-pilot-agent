-- B13-D: structured place references for must-visit / avoid lists.
--
-- Parallel and index-aligned with must_visit_places / avoid_places.  Old
-- rows keep NULL (legacy free text is never upgraded); anchor place refs
-- ride inside the arrival / departure / accommodation JSONB objects, so no
-- extra anchor columns are needed.

ALTER TABLE business.trip_constraint
    ADD COLUMN must_visit_place_refs JSONB,
    ADD COLUMN avoid_place_refs JSONB;

-- A place ref may only exist when the constraint schema explicitly carries
-- it (schemaVersion 3); legacy rows stay at schemaVersion 2.
UPDATE business.trip_constraint
SET schema_version = 3
WHERE must_visit_place_refs IS NOT NULL
   OR avoid_place_refs IS NOT NULL;
