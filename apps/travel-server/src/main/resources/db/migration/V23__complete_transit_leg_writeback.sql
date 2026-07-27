ALTER TABLE business.transit_leg
    DROP CONSTRAINT ck_transit_leg_mode;

ALTER TABLE business.transit_leg
    ADD CONSTRAINT ck_transit_leg_mode CHECK (
        mode IN ('WALKING', 'TRANSIT', 'DRIVING', 'TAXI')
    );

ALTER TABLE business.transit_leg
    ADD COLUMN estimated_cost NUMERIC(12, 2) NOT NULL DEFAULT 0,
    ADD COLUMN provider_route_id VARCHAR(160),
    ADD COLUMN calculated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ADD COLUMN stale BOOLEAN NOT NULL DEFAULT FALSE,
    ADD CONSTRAINT ck_transit_leg_estimated_cost CHECK (
        estimated_cost >= 0
    );
