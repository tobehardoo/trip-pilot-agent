CREATE SCHEMA IF NOT EXISTS business;

CREATE TABLE business.user_account (
    id UUID PRIMARY KEY,
    email VARCHAR(254) NOT NULL UNIQUE,
    password_hash VARCHAR(100) NOT NULL,
    display_name VARCHAR(80) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE business.refresh_token (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES business.user_account(id) ON DELETE CASCADE,
    token_hash CHAR(64) NOT NULL UNIQUE,
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    replaced_by UUID REFERENCES business.refresh_token(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_refresh_token_user_id ON business.refresh_token(user_id);

CREATE TABLE business.trip (
    id UUID PRIMARY KEY,
    owner_id UUID NOT NULL REFERENCES business.user_account(id) ON DELETE CASCADE,
    title VARCHAR(120) NOT NULL,
    destination VARCHAR(120) NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'DRAFT',
    version INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_trip_date_range CHECK (end_date >= start_date)
);

CREATE INDEX idx_trip_owner_updated ON business.trip(owner_id, updated_at DESC);

CREATE TABLE business.trip_constraint (
    trip_id UUID PRIMARY KEY REFERENCES business.trip(id) ON DELETE CASCADE,
    budget_amount NUMERIC(12, 2),
    travelers INTEGER NOT NULL DEFAULT 1,
    pace VARCHAR(20),
    preferences JSONB NOT NULL DEFAULT '[]'::jsonb,
    fixed_schedules JSONB NOT NULL DEFAULT '[]'::jsonb,
    schema_version INTEGER NOT NULL DEFAULT 1,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_trip_constraint_budget CHECK (budget_amount IS NULL OR budget_amount >= 0),
    CONSTRAINT ck_trip_constraint_travelers CHECK (travelers BETWEEN 1 AND 50)
);
