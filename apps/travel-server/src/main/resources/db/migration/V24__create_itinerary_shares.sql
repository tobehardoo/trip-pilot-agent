CREATE TABLE business.itinerary_share (
    id UUID PRIMARY KEY,
    itinerary_version_id UUID NOT NULL
        REFERENCES business.itinerary_version(id) ON DELETE CASCADE,
    trip_id UUID NOT NULL REFERENCES business.trip(id) ON DELETE CASCADE,
    owner_id UUID NOT NULL REFERENCES business.user_account(id) ON DELETE CASCADE,
    token_hash CHAR(64) NOT NULL UNIQUE,
    expires_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX itinerary_share_active_token_idx
    ON business.itinerary_share(token_hash)
    WHERE revoked_at IS NULL;

CREATE UNIQUE INDEX itinerary_share_one_active_version_idx
    ON business.itinerary_share(itinerary_version_id)
    WHERE revoked_at IS NULL;

CREATE INDEX itinerary_share_owner_trip_idx
    ON business.itinerary_share(owner_id, trip_id, created_at DESC);
