-- migrate:up
-- the book's structure is a tree of nodes, and a run reads it in pieces
ALTER TABLE toc_versions RENAME TO structure_versions;
ALTER SEQUENCE toc_versions_id_seq RENAME TO structure_versions_id_seq;
ALTER TABLE structure_versions RENAME CONSTRAINT toc_versions_pkey TO structure_versions_pkey;
ALTER TABLE structure_versions RENAME CONSTRAINT toc_versions_book_id_version_key TO structure_versions_book_id_version_key;
ALTER TABLE structure_versions RENAME CONSTRAINT toc_versions_book_id_fkey TO structure_versions_book_id_fkey;
ALTER INDEX toc_versions_one_current RENAME TO structure_versions_one_current;

ALTER TABLE toc_entries RENAME TO nodes;
ALTER SEQUENCE toc_entries_id_seq RENAME TO nodes_id_seq;
ALTER TABLE nodes RENAME COLUMN toc_version_id TO structure_version_id;
ALTER TABLE nodes RENAME CONSTRAINT toc_entries_pkey TO nodes_pkey;
ALTER TABLE nodes RENAME CONSTRAINT toc_entries_toc_version_id_ord_key TO nodes_structure_version_id_ord_key;
ALTER TABLE nodes RENAME CONSTRAINT toc_entries_toc_version_id_fkey TO nodes_structure_version_id_fkey;
ALTER TABLE nodes RENAME CONSTRAINT toc_entries_kind_check TO nodes_kind_check;
ALTER TABLE nodes RENAME CONSTRAINT toc_entries_level_check TO nodes_level_check;

ALTER TABLE chapters RENAME TO pieces;
ALTER TABLE pieces RENAME COLUMN toc_entry_id TO node_id;
ALTER TABLE pieces RENAME CONSTRAINT chapters_pkey TO pieces_pkey;
ALTER TABLE pieces RENAME CONSTRAINT chapters_run_id_fkey TO pieces_run_id_fkey;
ALTER TABLE pieces RENAME CONSTRAINT chapters_toc_entry_id_fkey TO pieces_node_id_fkey;
ALTER TABLE pieces RENAME CONSTRAINT chapters_status_check TO pieces_status_check;

ALTER TABLE runs RENAME COLUMN toc_version_id TO structure_version_id;
ALTER TABLE runs RENAME CONSTRAINT runs_toc_version_id_fkey TO runs_structure_version_id_fkey;
ALTER TABLE layout_versions RENAME COLUMN toc_version_id TO structure_version_id;
ALTER TABLE layout_versions RENAME CONSTRAINT layout_versions_toc_version_id_fkey
    TO layout_versions_structure_version_id_fkey;
ALTER TABLE artifacts RENAME COLUMN toc_version_id TO structure_version_id;
ALTER TABLE artifacts RENAME COLUMN chapter_ord TO piece_ord;
ALTER TABLE artifacts RENAME CONSTRAINT artifacts_toc_version_id_fkey TO artifacts_structure_version_id_fkey;
ALTER TABLE books RENAME COLUMN toc_sources TO structure_sources;
ALTER TABLE profiles RENAME COLUMN chapter_overrides TO piece_overrides;

UPDATE jobs SET type = 'read_piece' WHERE type = 'read_chapter';
UPDATE jobs SET type = 'assemble_piece' WHERE type = 'assemble_chapter';

-- migrate:down
UPDATE jobs SET type = 'assemble_chapter' WHERE type = 'assemble_piece';
UPDATE jobs SET type = 'read_chapter' WHERE type = 'read_piece';

ALTER TABLE profiles RENAME COLUMN piece_overrides TO chapter_overrides;
ALTER TABLE books RENAME COLUMN structure_sources TO toc_sources;
ALTER TABLE artifacts RENAME CONSTRAINT artifacts_structure_version_id_fkey TO artifacts_toc_version_id_fkey;
ALTER TABLE artifacts RENAME COLUMN piece_ord TO chapter_ord;
ALTER TABLE artifacts RENAME COLUMN structure_version_id TO toc_version_id;
ALTER TABLE layout_versions RENAME CONSTRAINT layout_versions_structure_version_id_fkey
    TO layout_versions_toc_version_id_fkey;
ALTER TABLE layout_versions RENAME COLUMN structure_version_id TO toc_version_id;
ALTER TABLE runs RENAME CONSTRAINT runs_structure_version_id_fkey TO runs_toc_version_id_fkey;
ALTER TABLE runs RENAME COLUMN structure_version_id TO toc_version_id;

ALTER TABLE pieces RENAME CONSTRAINT pieces_status_check TO chapters_status_check;
ALTER TABLE pieces RENAME CONSTRAINT pieces_node_id_fkey TO chapters_toc_entry_id_fkey;
ALTER TABLE pieces RENAME CONSTRAINT pieces_run_id_fkey TO chapters_run_id_fkey;
ALTER TABLE pieces RENAME CONSTRAINT pieces_pkey TO chapters_pkey;
ALTER TABLE pieces RENAME COLUMN node_id TO toc_entry_id;
ALTER TABLE pieces RENAME TO chapters;

ALTER TABLE nodes RENAME CONSTRAINT nodes_level_check TO toc_entries_level_check;
ALTER TABLE nodes RENAME CONSTRAINT nodes_kind_check TO toc_entries_kind_check;
ALTER TABLE nodes RENAME CONSTRAINT nodes_structure_version_id_fkey TO toc_entries_toc_version_id_fkey;
ALTER TABLE nodes RENAME CONSTRAINT nodes_structure_version_id_ord_key TO toc_entries_toc_version_id_ord_key;
ALTER TABLE nodes RENAME CONSTRAINT nodes_pkey TO toc_entries_pkey;
ALTER TABLE nodes RENAME COLUMN structure_version_id TO toc_version_id;
ALTER SEQUENCE nodes_id_seq RENAME TO toc_entries_id_seq;
ALTER TABLE nodes RENAME TO toc_entries;

ALTER INDEX structure_versions_one_current RENAME TO toc_versions_one_current;
ALTER TABLE structure_versions RENAME CONSTRAINT structure_versions_book_id_fkey TO toc_versions_book_id_fkey;
ALTER TABLE structure_versions RENAME CONSTRAINT structure_versions_book_id_version_key
    TO toc_versions_book_id_version_key;
ALTER TABLE structure_versions RENAME CONSTRAINT structure_versions_pkey TO toc_versions_pkey;
ALTER SEQUENCE structure_versions_id_seq RENAME TO toc_versions_id_seq;
ALTER TABLE structure_versions RENAME TO toc_versions;
