-- V27: Idempotency guard for itinerary edit confirmations.
-- Same pattern as V4 (planning tasks) and V22 (rollbacks).

CREATE TABLE business.itinerary_edit_idempotency (
    trip_id UUID NOT NULL REFERENCES business.trip(id) ON DELETE CASCADE,
    idempotency_key UUID NOT NULL,
    request_hash CHAR(64) NOT NULL,
    result_version_id UUID,
    status VARCHAR(20) NOT NULL DEFAULT 'COMPLETED',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (trip_id, idempotency_key)
);
