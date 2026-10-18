-- migrate:up
-- a node keeps the level the book gives it; only the Markdown writer caps headings at 6
ALTER TABLE nodes DROP CONSTRAINT nodes_level_check;
ALTER TABLE nodes ADD CONSTRAINT nodes_level_check CHECK (level >= 1);

-- migrate:down
ALTER TABLE nodes DROP CONSTRAINT nodes_level_check;
ALTER TABLE nodes ADD CONSTRAINT nodes_level_check CHECK (level >= 1 AND level <= 6);
