-- migrate:up
-- a job names the worker that claimed it, so a worker starting up requeues only its own or a dead one's jobs
ALTER TABLE jobs ADD COLUMN claimed_by text;
-- the lanes a worker serves, so the stand counts the threads of each lane and one worker at a time holds the GPU
ALTER TABLE workers ADD COLUMN lanes text NOT NULL DEFAULT 'cpu,gpu';

-- migrate:down
ALTER TABLE workers DROP COLUMN lanes;
ALTER TABLE jobs DROP COLUMN claimed_by;
