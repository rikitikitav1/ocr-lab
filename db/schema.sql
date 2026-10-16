--
-- PostgreSQL database dump
--

\restrict Cs1EXDRvEbGaiC3J2Cso4FqWvKr7oyAnGrS5l583cffWfHfkubuav6snFxi9fFz

-- Dumped from database version 17.10 (Debian 17.10-1.pgdg12+1)
-- Dumped by pg_dump version 17.10 (Debian 17.10-1.pgdg12+1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: public; Type: SCHEMA; Schema: -; Owner: -
--

-- *not* creating schema, since initdb creates it


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: artifacts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.artifacts (
    id bigint NOT NULL,
    run_id bigint,
    metadata_version_id bigint,
    structure_version_id bigint,
    book_id bigint,
    stage text NOT NULL,
    piece_ord integer,
    name text NOT NULL,
    path text NOT NULL,
    sha256 text NOT NULL,
    input_hash text NOT NULL,
    meta jsonb DEFAULT '{}'::jsonb NOT NULL,
    heavy boolean DEFAULT false NOT NULL,
    removed_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT artifacts_check CHECK ((num_nonnulls(run_id, metadata_version_id, structure_version_id) <= 1)),
    CONSTRAINT artifacts_check1 CHECK ((num_nonnulls(run_id, metadata_version_id, structure_version_id, book_id) >= 1))
);


--
-- Name: artifacts_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.artifacts ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.artifacts_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: book_files; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.book_files (
    book_id bigint NOT NULL,
    ord integer NOT NULL,
    sha256 text NOT NULL,
    file_path text NOT NULL,
    file_name text NOT NULL,
    pages integer NOT NULL,
    first_page integer NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: books; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.books (
    id bigint NOT NULL,
    sha256 text NOT NULL,
    pages integer,
    text_layer jsonb,
    has_bookmarks boolean,
    has_printed_contents boolean,
    structure_sources jsonb,
    stage text DEFAULT 'uploaded'::text NOT NULL,
    result_run_id bigint,
    knobs jsonb DEFAULT '{}'::jsonb NOT NULL,
    page_offset integer,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: books_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.books ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.books_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: jobs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.jobs (
    id bigint NOT NULL,
    type text NOT NULL,
    lane text NOT NULL,
    parent_id bigint,
    run_id bigint,
    book_id bigint,
    options jsonb DEFAULT '{}'::jsonb NOT NULL,
    status text DEFAULT 'new'::text NOT NULL,
    attempts integer DEFAULT 0 NOT NULL,
    reclaims integer DEFAULT 0 NOT NULL,
    apply_since timestamp with time zone DEFAULT now() NOT NULL,
    waiting_because jsonb,
    code_hash text,
    result jsonb,
    error jsonb,
    elapsed real,
    deferred_seconds integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT jobs_lane_check CHECK ((lane = ANY (ARRAY['gpu'::text, 'cpu'::text]))),
    CONSTRAINT jobs_status_check CHECK ((status = ANY (ARRAY['new'::text, 'running'::text, 'done'::text, 'error'::text, 'paused'::text, 'cancelled'::text])))
);


--
-- Name: jobs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.jobs ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.jobs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: layout_versions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.layout_versions (
    id bigint NOT NULL,
    book_id bigint NOT NULL,
    kind text NOT NULL,
    version integer NOT NULL,
    input_hash text NOT NULL,
    job_id bigint,
    current boolean DEFAULT false NOT NULL,
    structure_version_id bigint,
    layout jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT layout_versions_kind_check CHECK ((kind = ANY (ARRAY['page'::text, 'headings'::text])))
);


--
-- Name: layout_versions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.layout_versions ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.layout_versions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: metadata_fields; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.metadata_fields (
    metadata_version_id bigint NOT NULL,
    name text NOT NULL,
    value jsonb,
    source text,
    confidence real,
    attempts jsonb DEFAULT '[]'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT metadata_fields_check CHECK (((value IS NOT NULL) OR (jsonb_array_length(attempts) > 0)))
);


--
-- Name: metadata_versions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.metadata_versions (
    id bigint NOT NULL,
    book_id bigint NOT NULL,
    version integer NOT NULL,
    input_hash text NOT NULL,
    job_id bigint,
    current boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: metadata_versions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.metadata_versions ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.metadata_versions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: model_calls; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.model_calls (
    request_hash text NOT NULL,
    provider text NOT NULL,
    model text NOT NULL,
    params jsonb DEFAULT '{}'::jsonb NOT NULL,
    response_path text NOT NULL,
    tokens_in integer,
    tokens_out integer,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: nodes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.nodes (
    id bigint NOT NULL,
    structure_version_id bigint NOT NULL,
    ord integer NOT NULL,
    title text NOT NULL,
    level integer NOT NULL,
    level_source text NOT NULL,
    first_page integer,
    last_page integer,
    kind text NOT NULL,
    votes jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    parent_ord integer,
    CONSTRAINT nodes_kind_check CHECK ((kind = ANY (ARRAY['node'::text, 'front_matter'::text]))),
    CONSTRAINT nodes_level_check CHECK (((level >= 1) AND (level <= 6)))
);


--
-- Name: nodes_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.nodes ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.nodes_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: outside_hosts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.outside_hosts (
    host text NOT NULL,
    until timestamp with time zone NOT NULL,
    reason text NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: pieces; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pieces (
    run_id bigint NOT NULL,
    ord integer NOT NULL,
    node_id bigint,
    status text DEFAULT 'pending'::text NOT NULL,
    engine text,
    checks jsonb DEFAULT '{}'::jsonb NOT NULL,
    errors jsonb DEFAULT '[]'::jsonb NOT NULL,
    seconds real,
    gpu_seconds real,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT pieces_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'running'::text, 'done'::text, 'failed'::text])))
);


--
-- Name: profiles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.profiles (
    id bigint NOT NULL,
    book_id bigint NOT NULL,
    preset text NOT NULL,
    "values" jsonb NOT NULL,
    piece_overrides jsonb DEFAULT '{}'::jsonb NOT NULL,
    sha256 text NOT NULL,
    parent_id bigint,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: profiles_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.profiles ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.profiles_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.runs (
    id bigint NOT NULL,
    book_id bigint NOT NULL,
    profile_id bigint,
    metadata_version_id bigint,
    structure_version_id bigint,
    format text DEFAULT 'markdown'::text NOT NULL,
    dir text NOT NULL,
    status text DEFAULT 'queued'::text NOT NULL,
    stage text,
    code_hash text,
    engine_builds jsonb DEFAULT '{}'::jsonb NOT NULL,
    bundle_dir text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    reading_level integer,
    CONSTRAINT runs_status_check CHECK ((status = ANY (ARRAY['queued'::text, 'running'::text, 'needs_attention'::text, 'done'::text, 'failed'::text, 'cancelled'::text])))
);


--
-- Name: runs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.runs ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.runs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: schema_migrations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.schema_migrations (
    version character varying NOT NULL
);


--
-- Name: structure_versions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.structure_versions (
    id bigint NOT NULL,
    book_id bigint NOT NULL,
    version integer NOT NULL,
    input_hash text NOT NULL,
    job_id bigint,
    current boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    depth integer DEFAULT 0 NOT NULL
);


--
-- Name: structure_versions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.structure_versions ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.structure_versions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: workers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.workers (
    host text NOT NULL,
    code text NOT NULL,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    seen_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: artifacts artifacts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.artifacts
    ADD CONSTRAINT artifacts_pkey PRIMARY KEY (id);


--
-- Name: book_files book_files_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.book_files
    ADD CONSTRAINT book_files_pkey PRIMARY KEY (book_id, ord);


--
-- Name: books books_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.books
    ADD CONSTRAINT books_pkey PRIMARY KEY (id);


--
-- Name: books books_sha256_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.books
    ADD CONSTRAINT books_sha256_key UNIQUE (sha256);


--
-- Name: jobs jobs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jobs
    ADD CONSTRAINT jobs_pkey PRIMARY KEY (id);


--
-- Name: layout_versions layout_versions_book_id_kind_version_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.layout_versions
    ADD CONSTRAINT layout_versions_book_id_kind_version_key UNIQUE (book_id, kind, version);


--
-- Name: layout_versions layout_versions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.layout_versions
    ADD CONSTRAINT layout_versions_pkey PRIMARY KEY (id);


--
-- Name: metadata_fields metadata_fields_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.metadata_fields
    ADD CONSTRAINT metadata_fields_pkey PRIMARY KEY (metadata_version_id, name);


--
-- Name: metadata_versions metadata_versions_book_id_version_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.metadata_versions
    ADD CONSTRAINT metadata_versions_book_id_version_key UNIQUE (book_id, version);


--
-- Name: metadata_versions metadata_versions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.metadata_versions
    ADD CONSTRAINT metadata_versions_pkey PRIMARY KEY (id);


--
-- Name: model_calls model_calls_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.model_calls
    ADD CONSTRAINT model_calls_pkey PRIMARY KEY (request_hash);


--
-- Name: nodes nodes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.nodes
    ADD CONSTRAINT nodes_pkey PRIMARY KEY (id);


--
-- Name: nodes nodes_structure_version_id_ord_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.nodes
    ADD CONSTRAINT nodes_structure_version_id_ord_key UNIQUE (structure_version_id, ord);


--
-- Name: outside_hosts outside_hosts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.outside_hosts
    ADD CONSTRAINT outside_hosts_pkey PRIMARY KEY (host);


--
-- Name: pieces pieces_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pieces
    ADD CONSTRAINT pieces_pkey PRIMARY KEY (run_id, ord);


--
-- Name: profiles profiles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.profiles
    ADD CONSTRAINT profiles_pkey PRIMARY KEY (id);


--
-- Name: runs runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runs
    ADD CONSTRAINT runs_pkey PRIMARY KEY (id);


--
-- Name: schema_migrations schema_migrations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.schema_migrations
    ADD CONSTRAINT schema_migrations_pkey PRIMARY KEY (version);


--
-- Name: structure_versions structure_versions_book_id_version_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.structure_versions
    ADD CONSTRAINT structure_versions_book_id_version_key UNIQUE (book_id, version);


--
-- Name: structure_versions structure_versions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.structure_versions
    ADD CONSTRAINT structure_versions_pkey PRIMARY KEY (id);


--
-- Name: workers workers_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workers
    ADD CONSTRAINT workers_pkey PRIMARY KEY (host);


--
-- Name: artifacts_lookup; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX artifacts_lookup ON public.artifacts USING btree (stage, name, input_hash) WHERE (removed_at IS NULL);


--
-- Name: jobs_claim; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX jobs_claim ON public.jobs USING btree (lane, apply_since) WHERE (status = 'new'::text);


--
-- Name: jobs_parent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX jobs_parent ON public.jobs USING btree (parent_id);


--
-- Name: jobs_run; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX jobs_run ON public.jobs USING btree (run_id);


--
-- Name: layout_versions_one_current; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX layout_versions_one_current ON public.layout_versions USING btree (book_id, kind) WHERE current;


--
-- Name: metadata_versions_one_current; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX metadata_versions_one_current ON public.metadata_versions USING btree (book_id) WHERE current;


--
-- Name: structure_versions_one_current; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX structure_versions_one_current ON public.structure_versions USING btree (book_id) WHERE current;


--
-- Name: artifacts artifacts_book_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.artifacts
    ADD CONSTRAINT artifacts_book_id_fkey FOREIGN KEY (book_id) REFERENCES public.books(id) ON DELETE CASCADE;


--
-- Name: artifacts artifacts_metadata_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.artifacts
    ADD CONSTRAINT artifacts_metadata_version_id_fkey FOREIGN KEY (metadata_version_id) REFERENCES public.metadata_versions(id) ON DELETE CASCADE;


--
-- Name: artifacts artifacts_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.artifacts
    ADD CONSTRAINT artifacts_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.runs(id) ON DELETE CASCADE;


--
-- Name: artifacts artifacts_structure_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.artifacts
    ADD CONSTRAINT artifacts_structure_version_id_fkey FOREIGN KEY (structure_version_id) REFERENCES public.structure_versions(id) ON DELETE CASCADE;


--
-- Name: book_files book_files_book_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.book_files
    ADD CONSTRAINT book_files_book_id_fkey FOREIGN KEY (book_id) REFERENCES public.books(id) ON DELETE CASCADE;


--
-- Name: books books_result_run; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.books
    ADD CONSTRAINT books_result_run FOREIGN KEY (result_run_id) REFERENCES public.runs(id) ON DELETE SET NULL;


--
-- Name: jobs jobs_book_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jobs
    ADD CONSTRAINT jobs_book_id_fkey FOREIGN KEY (book_id) REFERENCES public.books(id) ON DELETE SET NULL;


--
-- Name: jobs jobs_parent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jobs
    ADD CONSTRAINT jobs_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.jobs(id) ON DELETE SET NULL;


--
-- Name: jobs jobs_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jobs
    ADD CONSTRAINT jobs_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.runs(id) ON DELETE SET NULL;


--
-- Name: layout_versions layout_versions_book_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.layout_versions
    ADD CONSTRAINT layout_versions_book_id_fkey FOREIGN KEY (book_id) REFERENCES public.books(id) ON DELETE CASCADE;


--
-- Name: layout_versions layout_versions_structure_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.layout_versions
    ADD CONSTRAINT layout_versions_structure_version_id_fkey FOREIGN KEY (structure_version_id) REFERENCES public.structure_versions(id) ON DELETE SET NULL;


--
-- Name: metadata_fields metadata_fields_metadata_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.metadata_fields
    ADD CONSTRAINT metadata_fields_metadata_version_id_fkey FOREIGN KEY (metadata_version_id) REFERENCES public.metadata_versions(id) ON DELETE CASCADE;


--
-- Name: metadata_versions metadata_versions_book_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.metadata_versions
    ADD CONSTRAINT metadata_versions_book_id_fkey FOREIGN KEY (book_id) REFERENCES public.books(id) ON DELETE CASCADE;


--
-- Name: nodes nodes_structure_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.nodes
    ADD CONSTRAINT nodes_structure_version_id_fkey FOREIGN KEY (structure_version_id) REFERENCES public.structure_versions(id) ON DELETE CASCADE;


--
-- Name: pieces pieces_node_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pieces
    ADD CONSTRAINT pieces_node_id_fkey FOREIGN KEY (node_id) REFERENCES public.nodes(id);


--
-- Name: pieces pieces_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pieces
    ADD CONSTRAINT pieces_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.runs(id) ON DELETE CASCADE;


--
-- Name: profiles profiles_book_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.profiles
    ADD CONSTRAINT profiles_book_id_fkey FOREIGN KEY (book_id) REFERENCES public.books(id) ON DELETE CASCADE;


--
-- Name: profiles profiles_parent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.profiles
    ADD CONSTRAINT profiles_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.profiles(id);


--
-- Name: runs runs_book_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runs
    ADD CONSTRAINT runs_book_id_fkey FOREIGN KEY (book_id) REFERENCES public.books(id) ON DELETE CASCADE;


--
-- Name: runs runs_metadata_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runs
    ADD CONSTRAINT runs_metadata_version_id_fkey FOREIGN KEY (metadata_version_id) REFERENCES public.metadata_versions(id);


--
-- Name: runs runs_profile_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runs
    ADD CONSTRAINT runs_profile_id_fkey FOREIGN KEY (profile_id) REFERENCES public.profiles(id);


--
-- Name: runs runs_structure_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.runs
    ADD CONSTRAINT runs_structure_version_id_fkey FOREIGN KEY (structure_version_id) REFERENCES public.structure_versions(id);


--
-- Name: structure_versions structure_versions_book_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.structure_versions
    ADD CONSTRAINT structure_versions_book_id_fkey FOREIGN KEY (book_id) REFERENCES public.books(id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

\unrestrict Cs1EXDRvEbGaiC3J2Cso4FqWvKr7oyAnGrS5l583cffWfHfkubuav6snFxi9fFz

