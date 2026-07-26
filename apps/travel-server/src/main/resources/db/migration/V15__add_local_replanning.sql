ALTER TABLE business.planning_task
    ADD COLUMN baseline_itinerary_version_id UUID
        REFERENCES business.itinerary_version(id),
    ADD COLUMN impacted_dates JSONB;

ALTER TABLE business.planning_task
    ADD CONSTRAINT ck_planning_task_replan_context CHECK (
        (task_type = 'CREATE'
            AND baseline_itinerary_version_id IS NULL
            AND impacted_dates IS NULL)
        OR
        (task_type = 'REPLAN'
            AND baseline_itinerary_version_id IS NOT NULL
            AND jsonb_typeof(impacted_dates) = 'array'
            AND jsonb_array_length(impacted_dates) BETWEEN 1 AND 7)
    );

ALTER TABLE business.itinerary_version
    DROP CONSTRAINT ck_itinerary_version_source;

ALTER TABLE business.itinerary_version
    ADD CONSTRAINT ck_itinerary_version_source
        CHECK (version_source IN ('PLANNING_TASK', 'USER_EDIT', 'LOCAL_REPLAN'));
