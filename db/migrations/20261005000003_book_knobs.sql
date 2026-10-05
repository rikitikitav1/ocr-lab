-- migrate:up
-- book-level knob overrides, given at submission or later; run-level knobs live in profiles
ALTER TABLE books ADD COLUMN knobs jsonb NOT NULL DEFAULT '{}';

-- migrate:down
ALTER TABLE books DROP COLUMN knobs;
