CREATE UNIQUE INDEX guide_fact_identity_idx
    ON business.guide_fact(guide_import_id, category, statement);
