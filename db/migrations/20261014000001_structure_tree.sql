-- migrate:up
ALTER TABLE toc_entries ADD COLUMN parent_ord int;
ALTER TABLE toc_versions ADD COLUMN depth int NOT NULL DEFAULT 0;
-- a node's parent is the nearest node before it on a higher level
UPDATE toc_entries e SET parent_ord = (
    SELECT max(p.ord) FROM toc_entries p
    WHERE p.toc_version_id = e.toc_version_id AND p.ord < e.ord AND p.level < e.level
);
UPDATE toc_versions v SET depth = (SELECT coalesce(max(e.level), 0) FROM toc_entries e WHERE e.toc_version_id = v.id);

-- migrate:down
ALTER TABLE toc_versions DROP COLUMN depth;
ALTER TABLE toc_entries DROP COLUMN parent_ord;
