ALTER TABLE business.itinerary_version
    ALTER COLUMN planning_task_id DROP NOT NULL;

ALTER TABLE business.itinerary_version
    ADD COLUMN version_source VARCHAR(30) NOT NULL DEFAULT 'PLANNING_TASK';

ALTER TABLE business.itinerary_version
    ADD CONSTRAINT ck_itinerary_version_source
        CHECK (version_source IN ('PLANNING_TASK', 'USER_EDIT'));

ALTER TABLE business.activity
    ADD COLUMN locked BOOLEAN NOT NULL DEFAULT FALSE;
