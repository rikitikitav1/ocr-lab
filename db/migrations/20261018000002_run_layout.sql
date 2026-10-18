-- migrate:up
-- a run reads the page layout it started on, as it reads its structure and metadata versions
ALTER TABLE runs ADD COLUMN layout_version_id bigint REFERENCES layout_versions(id);
-- the threads a worker's CPU lane runs, so the stand counts each worker's own
ALTER TABLE workers ADD COLUMN cpu_threads integer NOT NULL DEFAULT 4;

-- migrate:down
ALTER TABLE workers DROP COLUMN cpu_threads;
ALTER TABLE runs DROP COLUMN layout_version_id;
