ALTER TABLE business.outbox_event DROP CONSTRAINT ck_outbox_event_status;
ALTER TABLE business.outbox_event ADD CONSTRAINT ck_outbox_event_status CHECK (status IN ('PENDING', 'SENT', 'DEAD'));
