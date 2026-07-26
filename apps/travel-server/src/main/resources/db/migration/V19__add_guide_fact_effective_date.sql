ALTER TABLE business.guide_fact
    ADD COLUMN effective_date date;

CREATE INDEX idx_guide_fact_effective_date
    ON business.guide_fact(guide_import_id, effective_date)
    WHERE effective_date IS NOT NULL;
