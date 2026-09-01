-- Agent dialog event log (P2.7b): every consumed agent dialog event
-- (AGENT_ASK_USER / AGENT_STEP / AGENT_COMPLETED) lands here for the SSE
-- replay and the trajectory query API.  event_id is the consumer-side
-- idempotency key promised by the P2.1 resume semantics.

CREATE TABLE IF NOT EXISTS business.agent_dialog_message (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_id UUID NOT NULL,
    trip_id UUID NOT NULL,
    run_id UUID NOT NULL,
    event_type TEXT NOT NULL,
    schema_version INT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (event_id)
);

CREATE INDEX IF NOT EXISTS agent_dialog_message_trip_idx
    ON business.agent_dialog_message (trip_id, id);
