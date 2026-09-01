CREATE TABLE business.itinerary_feasibility_report (
    itinerary_version_id UUID PRIMARY KEY
        REFERENCES business.itinerary_version(id) ON DELETE CASCADE,
    report_id UUID NOT NULL UNIQUE,
    schema_version INTEGER NOT NULL,
    validator_version VARCHAR(32) NOT NULL,
    itinerary_fingerprint CHAR(64) NOT NULL,
    status VARCHAR(20) NOT NULL,
    validated_at TIMESTAMPTZ NOT NULL,
    report_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE business.itinerary_feasibility_report
    ADD CONSTRAINT ck_ifr_status_verified_only
    CHECK (status = 'VERIFIED');

ALTER TABLE business.itinerary_feasibility_report
    ADD CONSTRAINT ck_ifr_schema_version
    CHECK (schema_version = 1);

ALTER TABLE business.itinerary_feasibility_report
    ADD CONSTRAINT ck_ifr_fingerprint_lower_hex
    CHECK (itinerary_fingerprint ~ '^[0-9a-f]{64}$');

ALTER TABLE business.itinerary_feasibility_report
    ADD CONSTRAINT ck_ifr_report_json_object
    CHECK (jsonb_typeof(report_json) = 'object');

ALTER TABLE business.itinerary_feasibility_report
    ADD CONSTRAINT ck_ifr_report_json_matches_columns
    CHECK (
        report_json->>'reportId' IS NOT NULL
        AND (report_json->>'reportId')::uuid = report_id
        AND report_json->>'status' = status
        AND report_json->>'itineraryFingerprint' = itinerary_fingerprint
        AND (report_json->>'schemaVersion')::integer = schema_version
    );
