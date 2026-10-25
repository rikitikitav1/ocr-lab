-- migrate:up
-- the tree level a new run reads at unless the owner's knob says another, set when the structure is collected
ALTER TABLE structure_versions ADD COLUMN reading_level int NOT NULL DEFAULT 0;

-- migrate:down
ALTER TABLE structure_versions DROP COLUMN reading_level;
