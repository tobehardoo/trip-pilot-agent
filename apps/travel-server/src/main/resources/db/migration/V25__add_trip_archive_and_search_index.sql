ALTER TABLE business.trip
    ADD COLUMN archived_at TIMESTAMPTZ;

CREATE INDEX trip_owner_active_updated_idx
    ON business.trip (owner_id, updated_at DESC, id)
    WHERE archived_at IS NULL;

CREATE INDEX trip_owner_archived_updated_idx
    ON business.trip (owner_id, archived_at, updated_at DESC, id);
