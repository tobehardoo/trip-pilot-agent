-- Agent run trajectory, idempotency and checkpoint storage (P1.6 / P1.7).
-- Python-side only: lives in the existing `agent` schema, never touches the
-- Java business schema.

CREATE TABLE IF NOT EXISTS agent.agent_run (
    run_id TEXT PRIMARY KEY,
    command_event_id TEXT,
    trip_id TEXT,
    status TEXT NOT NULL,
    stop_reason TEXT,
    answer TEXT,
    pending_question TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Idempotency key (P1.6): one command event may start at most one run.
CREATE UNIQUE INDEX IF NOT EXISTS agent_run_command_event_id_key
    ON agent.agent_run (command_event_id)
    WHERE command_event_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS agent.agent_step (
    step_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES agent.agent_run (run_id) ON DELETE CASCADE,
    seq INT NOT NULL,
    kind TEXT NOT NULL,
    tool TEXT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (run_id, seq)
);

-- Latest restorable snapshot of the loop's working memory (P1.7).
CREATE TABLE IF NOT EXISTS agent.agent_checkpoint (
    run_id TEXT PRIMARY KEY REFERENCES agent.agent_run (run_id) ON DELETE CASCADE,
    steps INT NOT NULL,
    state JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
