-- migrate:up
CREATE TABLE layout_versions (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    book_id bigint NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    kind text NOT NULL CHECK (kind IN ('page', 'headings')),
    version int NOT NULL,
    input_hash text NOT NULL,
    job_id bigint,
    current boolean NOT NULL DEFAULT false,
    -- the structure whose pins gave the heading styles; only the headings layout has one
    toc_version_id bigint REFERENCES toc_versions(id) ON DELETE SET NULL,
    layout jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (book_id, kind, version)
);
CREATE UNIQUE INDEX layout_versions_one_current ON layout_versions (book_id, kind) WHERE current;

-- migrate:down
DROP TABLE layout_versions;
