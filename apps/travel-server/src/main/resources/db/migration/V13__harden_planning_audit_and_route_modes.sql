ALTER TABLE business.planning_task
    ADD COLUMN guide_evidence_snapshot JSONB NOT NULL
        DEFAULT '{"facts":[]}'::jsonb;

ALTER TABLE business.transit_leg
    DROP CONSTRAINT ck_transit_leg_mode;

ALTER TABLE business.transit_leg
    ADD CONSTRAINT ck_transit_leg_mode
        CHECK (mode IN ('WALKING', 'DRIVING'));
