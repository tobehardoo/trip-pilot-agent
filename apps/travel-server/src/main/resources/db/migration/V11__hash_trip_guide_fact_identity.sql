CREATE EXTENSION IF NOT EXISTS pgcrypto;

DROP INDEX business.guide_fact_identity_idx;

ALTER TABLE business.guide_fact
    ADD COLUMN statement_hash CHAR(64)
        GENERATED ALWAYS AS (encode(digest(statement, 'sha256'), 'hex')) STORED;

CREATE UNIQUE INDEX guide_fact_identity_idx
    ON business.guide_fact(guide_import_id, category, statement_hash);
