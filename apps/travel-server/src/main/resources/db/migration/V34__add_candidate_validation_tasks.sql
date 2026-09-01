ALTER TABLE business.planning_task
    ADD COLUMN candidate_type VARCHAR(20),
    ADD COLUMN candidate_source_version_id UUID
        REFERENCES business.itinerary_version(id),
    ADD COLUMN candidate_request_hash CHAR(64),
    ADD COLUMN changed_dates JSONB;

ALTER TABLE business.planning_task
    DROP CONSTRAINT ck_planning_task_type,
    ADD CONSTRAINT ck_planning_task_type CHECK (
        task_type IN ('CREATE', 'REPLAN', 'EDIT_VALIDATE', 'ROLLBACK_VALIDATE')
    ),
    DROP CONSTRAINT ck_planning_task_replan_context,
    ADD CONSTRAINT ck_planning_task_context CHECK (
        (task_type = 'CREATE'
            AND baseline_itinerary_version_id IS NULL
            AND impacted_dates IS NULL
            AND candidate_type IS NULL
            AND candidate_source_version_id IS NULL
            AND candidate_request_hash IS NULL
            AND changed_dates IS NULL)
        OR
        (task_type = 'REPLAN'
            AND baseline_itinerary_version_id IS NOT NULL
            AND jsonb_typeof(impacted_dates) = 'array'
            AND jsonb_array_length(impacted_dates) BETWEEN 1 AND 7
            AND candidate_type IS NULL
            AND candidate_source_version_id IS NULL
            AND candidate_request_hash IS NULL
            AND changed_dates IS NULL)
        OR
        (task_type IN ('EDIT_VALIDATE', 'ROLLBACK_VALIDATE')
            AND candidate_type = CASE task_type
                WHEN 'EDIT_VALIDATE' THEN 'EDIT'
                ELSE 'ROLLBACK'
            END
            AND baseline_itinerary_version_id IS NOT NULL
            AND candidate_source_version_id IS NOT NULL
            AND candidate_request_hash ~ '^[0-9a-f]{64}$'
            AND jsonb_typeof(changed_dates) = 'array'
            AND jsonb_array_length(changed_dates) BETWEEN 1 AND 7
            AND jsonb_typeof(impacted_dates) = 'array'
            AND jsonb_array_length(impacted_dates) BETWEEN 1 AND 7)
    );
