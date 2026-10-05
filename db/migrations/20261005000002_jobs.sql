-- migrate:up
CREATE TABLE jobs (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    type text NOT NULL,
    lane text NOT NULL CHECK (lane IN ('gpu', 'cpu')),
    parent_id bigint REFERENCES jobs(id) ON DELETE SET NULL,
    run_id bigint REFERENCES runs(id) ON DELETE SET NULL,
    book_id bigint REFERENCES books(id) ON DELETE SET NULL,
    options jsonb NOT NULL DEFAULT '{}',
    status text NOT NULL DEFAULT 'new'
        CHECK (status IN ('new', 'running', 'done', 'error', 'paused', 'cancelled')),
    attempts int NOT NULL DEFAULT 0,
    reclaims int NOT NULL DEFAULT 0,
    apply_since timestamptz NOT NULL DEFAULT now(),
    waiting_because jsonb,
    code_hash text,
    result jsonb,
    error jsonb,
    elapsed real,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX jobs_claim ON jobs (lane, apply_since) WHERE status = 'new';
CREATE INDEX jobs_parent ON jobs (parent_id);
CREATE INDEX jobs_run ON jobs (run_id);

-- migrate:down
DROP TABLE jobs;
