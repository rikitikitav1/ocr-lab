-- migrate:up
-- how long a job has waited on Deferred, kept apart from its options so they stay valid
ALTER TABLE jobs ADD COLUMN deferred_seconds int NOT NULL DEFAULT 0;

-- outside hosts set aside after failing every retry; shared by the api and the worker processes
CREATE TABLE outside_hosts (
    host text PRIMARY KEY,
    until timestamptz NOT NULL,
    reason text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- migrate:down
DROP TABLE outside_hosts;
ALTER TABLE jobs DROP COLUMN deferred_seconds;
