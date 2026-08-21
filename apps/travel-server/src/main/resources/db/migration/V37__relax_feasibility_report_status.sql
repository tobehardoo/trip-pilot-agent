-- B16: Information Missing != Planning Failed.
-- A savable feasibility report may be UNVERIFIED (opening hours / visit
-- duration unverified) or even NEEDS_REPAIR-recorded; only the explicit v10
-- hasBlocker decision (enforced by the application layer) prevents a blocker
-- report from ever being persisted.  This only relaxes the DB check - it
-- never changes existing rows - so it is a non-breaking, forward-only
-- constraint change.

ALTER TABLE business.itinerary_feasibility_report
    DROP CONSTRAINT ck_ifr_status_verified_only;

ALTER TABLE business.itinerary_feasibility_report
    ADD CONSTRAINT ck_ifr_status_supported
    CHECK (status IN ('VERIFIED', 'UNVERIFIED', 'NEEDS_REPAIR'));
