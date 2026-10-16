-- migrate:up
-- a node is the book's own or the front matter the code adds; its depth lives in level alone
ALTER TABLE nodes DROP CONSTRAINT nodes_kind_check;
UPDATE nodes SET kind = 'node' WHERE kind <> 'front_matter';
ALTER TABLE nodes ADD CONSTRAINT nodes_kind_check CHECK (kind = ANY (ARRAY['node'::text, 'front_matter'::text]));

-- migrate:down
-- the old kinds are not kept: a node goes back as a chapter at the top level and a section below it
ALTER TABLE nodes DROP CONSTRAINT nodes_kind_check;
UPDATE nodes SET kind = CASE WHEN parent_ord IS NULL THEN 'chapter' ELSE 'section' END WHERE kind = 'node';
ALTER TABLE nodes ADD CONSTRAINT nodes_kind_check CHECK (kind = ANY (ARRAY['chapter'::text, 'part'::text,
    'section'::text, 'front_matter'::text, 'back_matter'::text]));
