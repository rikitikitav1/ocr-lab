-- migrate:up
CREATE TABLE books (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sha256 text NOT NULL UNIQUE,
    pages int,
    text_layer jsonb,
    has_bookmarks boolean,
    has_printed_contents boolean,
    toc_sources jsonb,
    stage text NOT NULL DEFAULT 'uploaded',
    result_run_id bigint,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE book_files (
    book_id bigint NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    ord int NOT NULL,
    sha256 text NOT NULL,
    file_path text NOT NULL,
    file_name text NOT NULL,
    pages int NOT NULL,
    first_page int NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (book_id, ord)
);

CREATE TABLE metadata_versions (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    book_id bigint NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    version int NOT NULL,
    input_hash text NOT NULL,
    job_id bigint,
    current boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (book_id, version)
);
CREATE UNIQUE INDEX metadata_versions_one_current ON metadata_versions (book_id) WHERE current;

CREATE TABLE metadata_fields (
    metadata_version_id bigint NOT NULL REFERENCES metadata_versions(id) ON DELETE CASCADE,
    name text NOT NULL,
    value jsonb,
    source text,
    confidence real,
    attempts jsonb NOT NULL DEFAULT '[]',
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (metadata_version_id, name),
    -- an unknown field must say where it was looked for
    CHECK (value IS NOT NULL OR jsonb_array_length(attempts) > 0)
);

CREATE TABLE toc_versions (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    book_id bigint NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    version int NOT NULL,
    input_hash text NOT NULL,
    job_id bigint,
    current boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (book_id, version)
);
CREATE UNIQUE INDEX toc_versions_one_current ON toc_versions (book_id) WHERE current;

CREATE TABLE toc_entries (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    toc_version_id bigint NOT NULL REFERENCES toc_versions(id) ON DELETE CASCADE,
    ord int NOT NULL,
    title text NOT NULL,
    level int NOT NULL CHECK (level BETWEEN 1 AND 6),
    level_source text NOT NULL,
    first_page int,
    last_page int,
    kind text NOT NULL CHECK (kind IN ('chapter', 'part', 'section', 'front_matter', 'back_matter')),
    votes jsonb NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (toc_version_id, ord)
);

CREATE TABLE profiles (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    book_id bigint NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    preset text NOT NULL,
    "values" jsonb NOT NULL,
    chapter_overrides jsonb NOT NULL DEFAULT '{}',
    sha256 text NOT NULL,
    parent_id bigint REFERENCES profiles(id),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE runs (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    book_id bigint NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    profile_id bigint REFERENCES profiles(id),
    metadata_version_id bigint REFERENCES metadata_versions(id),
    toc_version_id bigint REFERENCES toc_versions(id),
    format text NOT NULL DEFAULT 'markdown',
    dir text NOT NULL,
    status text NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'running', 'needs_attention', 'done', 'failed', 'cancelled')),
    stage text,
    code_hash text,
    engine_builds jsonb NOT NULL DEFAULT '{}',
    verdict text CHECK (verdict IN ('ok', 'dirty', 'bad')),
    bundle_dir text,
    created_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE books ADD CONSTRAINT books_result_run FOREIGN KEY (result_run_id) REFERENCES runs(id) ON DELETE SET NULL;

CREATE TABLE chapters (
    run_id bigint NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    ord int NOT NULL,
    toc_entry_id bigint REFERENCES toc_entries(id),
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'running', 'done', 'failed')),
    engine text,
    checks jsonb NOT NULL DEFAULT '{}',
    verdict text CHECK (verdict IN ('ok', 'dirty', 'bad')),
    reasons jsonb NOT NULL DEFAULT '[]',
    seconds real,
    gpu_seconds real,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, ord)
);

CREATE TABLE artifacts (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id bigint REFERENCES runs(id) ON DELETE CASCADE,
    metadata_version_id bigint REFERENCES metadata_versions(id) ON DELETE CASCADE,
    toc_version_id bigint REFERENCES toc_versions(id) ON DELETE CASCADE,
    book_id bigint REFERENCES books(id) ON DELETE CASCADE,
    stage text NOT NULL,
    chapter_ord int,
    name text NOT NULL,
    path text NOT NULL,
    sha256 text NOT NULL,
    input_hash text NOT NULL,
    meta jsonb NOT NULL DEFAULT '{}',
    heavy boolean NOT NULL DEFAULT false,
    removed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    -- exactly one owner: a run, a book-level version, or the book itself for intake
    CHECK (num_nonnulls(run_id, metadata_version_id, toc_version_id) <= 1),
    CHECK (num_nonnulls(run_id, metadata_version_id, toc_version_id, book_id) >= 1)
);
CREATE INDEX artifacts_lookup ON artifacts (stage, name, input_hash) WHERE removed_at IS NULL;

CREATE TABLE model_calls (
    request_hash text PRIMARY KEY,
    provider text NOT NULL,
    model text NOT NULL,
    params jsonb NOT NULL DEFAULT '{}',
    response_path text NOT NULL,
    tokens_in int,
    tokens_out int,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- migrate:down
DROP TABLE model_calls, artifacts, chapters;
ALTER TABLE books DROP CONSTRAINT books_result_run;
DROP TABLE runs, profiles, toc_entries, toc_versions, metadata_fields, metadata_versions, book_files, books;
