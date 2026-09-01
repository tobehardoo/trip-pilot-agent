-- P3.2: cross-session user travel profile.  Model-proposed preferences land
-- as PENDING; only user-confirmed entries (evidence-match rule, same trust
-- model as constraint slots) are ever injected into decisions, and REVOKED
-- entries never revive by re-proposal.

CREATE TABLE IF NOT EXISTS agent.user_travel_profile (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id UUID NOT NULL,
    category TEXT NOT NULL,
    value TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, category, value)
);

CREATE INDEX IF NOT EXISTS user_travel_profile_user_idx
    ON agent.user_travel_profile (user_id, status);
