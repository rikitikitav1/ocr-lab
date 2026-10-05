---

description: "Task list for PDF Book to Measured Markdown Bundle"
---

# Tasks: PDF Book to Measured Markdown Bundle

**Input**: Design documents from `specs/001-pdf-book-to-markdown/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: included. The constitution (Development Workflow) requires every check a principle names
to be enforced by an automated test or a report field, and SC-005 names a kill-and-resume test.

**Organization**: grouped by user story in the spec's priority order P0 to P5 (labels US0 to US5).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: user story the task belongs to (US0 to US5)
- Paths are relative to the repository root, layout as in plan.md

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: repository, build, stand skeleton

- [x] T001 Move `rag-lab-intake/` to `~/working_docs/projects/ocr-lab/notes/rag-lab-intake/`, run `git init`, and write `.gitignore` with `creds-shared.db`, `data/`, `.env`, `__pycache__/`, `.venv/`, `temp_files/` (plan.md, Delivery order)
- [x] T002 Create `pyproject.toml` for Python 3.12 with uv and hatchling (`[tool.hatch.build.targets.wheel] sources=["app"]`), dependencies from plan.md Technical Context (fastapi, uvicorn, fastmcp, sqlalchemy, psycopg[binary], pydantic, pypdfium2, rapidfuzz, lingua-language-detector, wordfreq, httpx, openai, pyyaml), dev group (pytest, pytest-xdist, ruff, reportlab), then `uv lock`
- [x] T003 [P] Create `Dockerfile` on `python:3.12-slim` pinned by digest, uv binary copied from `ghcr.io/astral-sh/uv`, `uv sync --frozen` into `/opt/venv`, workdir `/app`
- [x] T004 Create `docker-compose.yml`: `postgres` (postgres:17, healthcheck `pg_isready`, volume `pg_data`), one-shot `dbmate` (2.34.1, `./db:/db`, `DBMATE_NO_DUMP_SCHEMA=true`), `api` (uvicorn `server:app` on 8100, bind mount `.:/app`), `worker` (`restart: unless-stopped`, host UID/GID), `converter-docling` and `converter-mineru` with `image: rag-lab-converter-docling` / `rag-lab-converter-mineru`, `pull_policy: never`, profile `convert`, `init: true`, `stop_grace_period: 45s`, GPU anchor `x-gpu` (CDI `nvidia.com/gpu=all`), `ollama` using external volume `rag-lab_ollama_data`; read-only mounts `${HOME}/.cache/huggingface`, `../rag-lab/datasets/inbox/books` as `/shelf/books`, `../rag-lab/datasets/converter_gold` as `/shelf/gold`; volume `./data:/data` (research R5)
- [x] T005 [P] Create `.env.example` with `DATABASE_URL`, `MODEL_PROVIDERS` (ollama URL, OpenAI-compatible cloud URL and key), `CPU_LANE_THREADS=4`, shelf paths (research R12)
- [x] T006 [P] Configure ruff in `pyproject.toml` (line-length 120, select E4/E5/E7/E9/F/I/B) and write `scripts/check.sh` running `ruff check`, then `pytest -n 8`
- [x] T007 [P] Create `tests/real_db.py` (scratch database per module `CREATE DATABASE ocrtest_<uuid>` from `db/schema.sql` on `TEST_POSTGRES_URL`, skip when Postgres is unreachable) and `tests/conftest.py` with a FastAPI `TestClient` fixture (research R13)
- [x] T008 [P] Create `tests/repo/test_house_rules.py`: code comments carry no commit references, no plan section or arc numbers, no dates, no emoji

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: catalogue tables, queue, artifacts, doors skeleton, engines, model client. No user
story starts before this phase is done.

- [x] T009 Write `db/migrations/20261005000001_catalogue.sql` for `books` (`sha256 text unique`: hash of the ordered file sha256 list; `pages`, `text_layer jsonb`, `has_bookmarks`, `has_printed_contents`, `toc_sources jsonb`, `stage`, `result_run_id`), `book_files` (unique `(book_id, ord)`, `first_page`), `metadata_versions` and `toc_versions` (`version`, `input_hash`, `job_id`, `current bool`, one current per book and kind), `metadata_fields` (unique `(metadata_version_id, name)`, `value jsonb` null when unknown, `source`, `confidence real`, `attempts jsonb`), `toc_entries` (`level` 1..6, `level_source`, `kind`, `votes jsonb`), `profiles` (immutable, `values jsonb`, `chapter_overrides jsonb`, `sha256`, `parent_id`), `runs` (`metadata_version_id`, `toc_version_id`, `status`, `stage`, `code_hash`, `engine_builds jsonb`, `verdict`, `bundle_dir`), `chapters` (unique `(run_id, ord)`), `artifacts` (exactly one owner: `run_id` or a version id; `sha256`, `input_hash`, `heavy bool`, `removed_at`), `model_calls` (`request_hash` pk) as in data-model.md; regenerate `db/schema.sql`
- [x] T010 Write `db/migrations/20261005000002_jobs.sql` for `jobs` (`type`, `lane` in (`gpu`, `cpu`), `parent_id`, `run_id`, `options jsonb`, `status` in (`new`, `running`, `done`, `error`, `paused`, `cancelled`), `attempts`, `apply_since`, `waiting_because`, `code_hash`, `result`, `error`, `elapsed`) with an index for claiming; regenerate `db/schema.sql`
- [x] T011 [P] Create SQLAlchemy tables for the catalogue in `app/orm/catalogue.py` and the session factory in `app/orm/db.py`
- [x] T012 [P] Create SQLAlchemy table for jobs in `app/orm/jobs.py`
- [x] T013 Implement `app/artifacts.py`: write to a `.tmp` sibling, fsync, rename, then insert the manifest row; `input_hash(inputs, profile_sha, engine_builds)`; `find_done(owner, stage, chapter, name, input_hash)` returns a row only if the file exists and its sha matches; paths `data/books/<book_id>/<metadata|toc>/v<N>/` and `data/runs/<book_id>/<run_id>/<stage>/[<chapter>/]` (research R3, FR-020, FR-022)
- [x] T014 Implement `app/job_queue.py`: `enqueue` (validated by `app/job_specs.py`), `claim_next(lane)` with `FOR UPDATE SKIP LOCKED`, `reschedule` (backoff `60*attempts` s, attempt budget per job type read from `config/budgets.yaml`, 3 to 5, FR-057), `Deferred` (no attempt counted, up to 3600 s) and `Final`, `requeue_stale`, `cancel`/`pause`/`resume`, `pg_notify('job_changed', ...)` on every state change, `wait(job_id, timeout)` returning when the job and all its children are finished (research R4)
- [x] T015 [P] Create `config/budgets.yaml` (attempts per stage: `intake`, `metadata`, `toc`, `profile_search`, `assemble_chapter`, `book_metrics`, `eval_run`, each 3 to 5, validated at start) and `app/job_specs.py`: pydantic option specs and lane per job type (`book_run`, `intake`, `metadata`, `toc`, `profile_search`, `assemble_chapter`, `book_metrics`, `eval_run`, `cleanup`)
- [x] T016 Implement `app/worker.py`: one serial thread for lane `gpu`, `CPU_LANE_THREADS` threads for lane `cpu`, handler registry `@register`, hash of `app/` at start stamped on every claimed job, refuse new jobs and report when the code on disk differs (research R4)
- [x] T017 Implement `app/server.py` (FastAPI, routers under `/v1`, FastMCP server mounted at `/mcp` with stateless HTTP and chained lifespan) and `app/mcp_tools.py` with a helper that registers a tool for a use case function
- [x] T018 [P] Implement jobs doors in `app/api/v1/jobs.py` and their tools: `GET /jobs`, `GET /jobs/{id}`, `GET /jobs/{id}/wait`, `POST /jobs/pause|resume|cancel`, `GET /queue` (contracts/http_api.md, contracts/mcp_tools.md)
- [x] T019 Copy rag-lab engines into `app/engines/` (`converter.py` with `take_once`, `let_go`, `reading`; `converter_tools.py` for docling-serve and MinerU HTTP APIs; `card.py` with `hand_to`; `stamps.py`) and adapt: calls take an explicit file page range, every reading returns the engine build stamp from `GET /supervisor` and fails without one (research R7a, plan.md Constitution Check)
- [x] T020 [P] Implement `app/models_client.py`: OpenAI-compatible chat client, provider chosen per step, cache by request hash in `model_calls` plus an artifact, record provider, model id and parameters, raise `Deferred` on unavailable or rate-limited provider (research R12, FR-026)
- [x] T021 [P] Implement stand door `GET /v1/stand` in `app/api/v1/stand.py` with tool `stand()`: services health, engine builds, GPU holder, worker code hash against disk, shelf mounts
- [x] T022 [P] Create `tests/doors/test_parity.py`: every REST route under `/v1` has an MCP tool with the same use case and every tool has a route (contracts/mcp_tools.md)
- [x] T023 [P] Create `tests/unit/test_artifacts.py`: a crash between tmp write and rename leaves no manifest row; `find_done` rejects a changed input hash and a file whose sha differs
- [x] T024 [P] Create `tests/unit/test_job_queue.py`: two claimers never get the same job, backoff and `Deferred` semantics, `wait` returns on child completion, stale running jobs are requeued

**Checkpoint**: stand comes up, jobs run on both lanes, doors and tools respond.

---

## Phase 3: User Story 0 - Stand up the stand and catalogue a book (Priority: P0)

**Goal**: one command brings the stand up without downloads; a submitted PDF (one or several
files) becomes a catalogue record with complete metadata.

**Independent Test**: bring the stand up on a machine with the rag-lab downloads, submit a book
with bookmarks, one without, one scan and one two-file book; each record shows every metadata
field with source and confidence, or unknown with every source tried (quickstart.md steps 1 and 2).

### Tests for User Story 0

- [x] T025 [P] [US0] Create `tests/stages/test_intake.py`: same files in the same order map to one book, different order or one extra file to another; pages run across files with `(file ord, in-file page)` kept; text layer per page detected on a reportlab fixture with one raster page
- [x] T026 [P] [US0] Create `tests/stages/test_metadata.py`: ISBN-10 and ISBN-13 checksum, year, publisher, edition, series and volume patterns in Russian and English title pages; a field left unknown lists every applicable source in `attempts`; conflicting sources resolved by field priority with the conflict in evidence
- [x] T027 [P] [US0] Create `tests/doors/test_books.py`: `POST /books` returns 201 then 200 for the same files; `PATCH /books/{id}/metadata/{name}` creates a new metadata version with source `manual` and keeps found values in evidence; `GET /books?series=` sorts by volume

### Implementation for User Story 0

- [x] T028 [US0] Implement `app/stages/intake.py`: store each file under `data/files/<sha[:2]>/<sha>.pdf`, compute book identity from the ordered file hashes, fill `book_files` with `first_page`, read pages, per-page text layer and bookmarks presence with pypdfium2, probe printed contents with the dot-leader parser ported from rag-lab `route.contents_outline`, write intake artifacts (FR-036, FR-054)
- [x] T029 [US0] Implement `app/use_cases/books.py` (`add_book` from uploaded files or shelf paths, `list_books` with `stage`, `verdict`, `q`, `series` filters, `get_book`) and doors `POST /books`, `GET /books`, `GET /books/{id}` in `app/api/v1/books.py` with tools `add_book`, `books`, `book`
- [x] T030 [P] [US0] Implement metadata source `app/stages/metadata/file_metadata.py` (PDF info dictionary and XMP of every file)
- [x] T031 [P] [US0] Implement metadata source `app/stages/metadata/title_pages.py`: text of the first and last 12 pages (recognised text for pages without a layer, through a `gpu` lane reading of those pages only), ISBN by regex with checksum (a 10-digit one only next to an `ISBN` label), `original_isbn` for translations, year, publisher, edition, series and volume by per-language patterns; junk PDF metadata (`*.dvi`, `Microsoft Word - `, the file name) ignored
- [x] T032 [P] [US0] Implement metadata source `app/stages/metadata/catalogues.py`: Open Library (English) and Labirint (Russian) by ISBN then by title and author, Google Books when `GOOGLE_BOOKS_API_KEY` is set; each lookup recorded as an attempt with outcome `found`, `absent`, `conflict` or `failed`
- [x] T033 [P] [US0] Implement `app/stages/metadata/model_reader.py` (stand model reads title and copyright pages for fields still missing or in conflict, JSON output) and `app/stages/metadata/subject.py` (free label such as "databases, textbook" or "detective novel")
- [x] T034 [P] [US0] Implement `app/stages/metadata/language.py` with lingua over body text, per-language share for mixed books
- [x] T035 [US0] Implement `app/stages/metadata/resolve.py`: run every source for every field before giving up, fixed source priority per field, write a new `metadata_versions` row with `input_hash` of metadata knobs and source code hash, never guess a value (FR-037, FR-038, FR-052)
- [x] T036 [US0] Register job handlers `intake` and `metadata` in `app/job_handlers/book.py`, chained after `POST /books`; then `toc` (T053) in the same chain; book stage moves `uploaded → metadata → toc → ready`
- [x] T037 [US0] Implement manual metadata edit in `app/use_cases/metadata.py` and door `PATCH /books/{id}/metadata/{name}` with tool `set_metadata`: new version, source `manual`, found values kept in evidence (FR-051)
- [x] T038 [US0] Implement `GET /books/{id}/metadata` and `POST /books/{id}/recollect` (`{"what": ["metadata", "toc"]}`) with tools; recollection also triggers when the stored `input_hash` no longer matches current knobs and source code (FR-052)
- [x] T039 [US0] Create `tests/stand/test_compose_smoke.py` (marked `stand`): `docker compose --profile convert up` pulls no image, `/v1/stand` shows both converter build stamps (SC-009)
- [x] T040 [US0] Book-level knobs (FR-059): `books.knobs` column, `app/book_knobs.py` with defaults from `config/metadata.yaml` (title-page window 20 and 20), knobs at submission and `PATCH /v1/books/{id}/knobs` with tool `set_book_knobs`, printed contents pages given by hand recorded at intake (tests in `tests/doors/test_books.py`)

**Checkpoint**: books enter the catalogue with complete metadata through REST and MCP.

---

## Phase 4: User Story 1 - Feed a PDF, get a measured Markdown bundle (Priority: P1) 🎯 MVP

**Goal**: a catalogued book becomes a bundle (Markdown, `images/`, `profile.yaml`, `report.json`,
`report.md`) assembled chapter by chapter from a reconciled table of contents, with a verdict.

**Independent Test**: convert a PDF with bookmarks; chapters in the document match the bookmarks,
every image link resolves after moving the bundle, the report carries a verdict with reasons;
rerun one chapter with an override (quickstart.md steps 3, 4, 6).

### Tests for User Story 1

- [ ] T041 [P] [US1] Create `tests/unit/test_reconcile.py`: entries matched across sources by normalised title and page, printed page offset resolved, level from the highest-ranked source with that source stamped, front and back matter kept with their `kind`
- [ ] T042 [P] [US1] Create `tests/unit/test_document_model.py`: headings outside 1..6 rejected; chapter inner levels relative to the chapter level (FR-004, FR-043)
- [ ] T043 [P] [US1] Create `tests/unit/test_markdown_writer.py`: title `#`, chapters `##` or parts `##` with chapters `###`; notes as `> **Note:**` blockquotes; chapter marker comments; relative image links
- [ ] T044 [P] [US1] Create `tests/unit/test_verdicts.py`: book verdict is the worst of chapter verdicts and whole-book checks; `ok` impossible with a missing chapter, a chapter below its own section, or a flat chapter whose toc shows sections (FR-019, FR-045)
- [ ] T045 [P] [US1] Create `tests/stages/test_bundle.py`: `report.json` matches contracts/bundle.md schema 1; `scripts/check_links.py` finds zero broken links and zero unreferenced images after moving the bundle (SC-004)

### Implementation for User Story 1

- [ ] T046 [P] [US1] Implement toc source `app/stages/toc/sources/bookmarks.py`: outline of each file placed under the file's position (FR-054)
- [ ] T047 [P] [US1] Implement toc source `app/stages/toc/sources/printed_contents.py`: dot-leader parser plus the stand model reading contents pages without dot leaders
- [ ] T048 [P] [US1] Implement toc source `app/stages/toc/sources/numbering.py` (PART, CHAPTER, ГЛАВА, Roman and dotted decimal grammar)
- [ ] T049 [P] [US1] Implement toc source `app/stages/toc/sources/typography.py`: whole-book style profile ported from `book_levels_proto.py` (body size is the mode, styles with fewer than 10 items merge into the nearest common one, text on 20+ pages is a running head, level = rank + 1 clamped to 6)
- [ ] T050 [P] [US1] Implement toc source `app/stages/toc/sources/catalogue.py` (Open Library `table_of_contents`, publisher pages)
- [ ] T051 [P] [US1] Implement toc source `app/stages/toc/sources/model_levels.py`: the stand model assigns levels over the list of heading candidates, used last
- [ ] T052 [US1] Implement `app/stages/toc/reconcile.py` (rapidfuzz title match, page offset maximising matches, per-entry level from the highest-ranked source, `votes`) and `app/stages/toc/filter.py` (kinds `chapter`, `part`, `section`, `front_matter`, `back_matter`); write a new `toc_versions` row and per-source artifacts (FR-008, FR-009)
- [ ] T053 [US1] Register job handler `toc` in `app/job_handlers/book.py` and door `GET /books/{id}/toc` (`source`, `version`) with tool `toc`; `book_run` enqueues `toc` itself when the book has no current toc version (FR-039, FR-052)
- [ ] T054 [P] [US1] Write `scripts/fetch_toc_gold.py` (job `fetch_gold`, CPU lane): HiPS PDFs and `GT_TOCs` (`Level, Heading, Page`) at a pinned commit into `data/gold/hips/` (CC BY-NC data, never committed); LongDocBench into `data/gold/longdocbench/` when a data link exists, otherwise record its absence (research R16)
- [ ] T055 [US1] Implement `app/evaluation/toc_gold.py`: score a toc version against a gold TOC: entry recall and precision by fuzzy title plus page, level agreement on matched entries, TEDS over the TOC tree (FR-058)
- [ ] T056 [US1] Register job `toc_eval` and door `POST /v1/eval/toc` with tool `toc_eval` (`set`: `hips`, `longdocbench`, `bookmarks_off` over shelf books with bookmarks): runs intake and toc on each book, writes per-book scores and a summary artifact; works before chapter assembly exists
- [ ] T057 [P] [US1] Create `tests/unit/test_toc_gold.py`: identical trees score TEDS 1.0; a shifted level lowers level agreement and TEDS; a missing entry lowers recall; an extra entry lowers precision
- [ ] T058 [P] [US1] Implement the document model in `app/document/model.py`: pydantic blocks heading (`level` 1..6, `level_source`), paragraph, code, table, list, figure (`image` ref), caption, note, page marker with `(file ord, in-file page)`
- [ ] T059 [P] [US1] Implement `app/knobs/registry.py` loading `config/knobs.yaml` (groups, knobs, options bound to registered functions, `help`, `probe`, `cost`, `scope`) and `config/presets/default.yaml` selecting no genre-specific rule (FR-011, FR-050)
- [ ] T060 [US1] Implement `app/profiles.py`: resolve preset plus overrides into an immutable profile with `sha256`, every value with `source` and `evidence`; `chapter_overrides`; `derive` (FR-012, FR-014)
- [ ] T061 [P] [US1] Implement `app/engines/docling_adapter.py`: docling-serve JSON of a chapter page range into the document model
- [ ] T062 [P] [US1] Implement `app/engines/mineru_adapter.py`: MinerU output of a page range into the document model
- [ ] T063 [P] [US1] Implement rules in `app/rules/`: `running_heads.py`, `duplicate_pages.py`, `decorative_images.py` (same image hash on many pages), `code_from_layer.py`, `sidebars.py`, `captions.py` (captions never become headings, FR-006), `chapter_levels.py` (levels relative to the toc entry); each a knob option, each writes the model after it as a heavy artifact
- [ ] T064 [US1] Implement `app/stages/assemble.py`: one chapter = engine by knob (text layer → Docling, no layer → MinerU), page ranges split at the knob page count with continuation marked, adapter, rules in profile order, images saved as `images/<chapter_ord>-<n>.<ext>`, chapter checks, chapter verdict (FR-042, FR-031, FR-033)
- [ ] T065 [P] [US1] Implement chapter checks in `app/quality/chapter.py`: structure against toc sub-entries, flat-chapter check (`structure.flat`), heading sanity, `layer_f1` on text pages, image link integrity; thresholds in `config/quality.yaml`
- [ ] T066 [P] [US1] Implement scan measures in `app/quality/scans.py`: agreement of two engines on the same pages, `wordfreq` dictionary share for the book's language, engine confidence where given, per page range (FR-032)
- [ ] T067 [P] [US1] Implement `app/writers/markdown.py` per contracts/bundle.md (levels, fenced code, pipe or HTML tables, notes as blockquotes, chapter marker comments, relative image links)
- [ ] T068 [US1] Implement `app/stages/book_metrics.py`: aggregate chapters, whole-book checks (chapters against toc, duplicates across chapters, images), worst verdict with reasons naming chapters, write bundle `data/bundles/<book_id>/<run_id>/` with `<slug>.md`, `images/`, `profile.yaml`, `report.json`, `report.md`, then recompute the book's `result_run_id` (FR-045, FR-053)
- [ ] T069 [US1] Implement run orchestration in `app/job_handlers/run.py`: `book_run` uses current metadata and toc versions and records them, enqueues `assemble_chapter` per chapter ordered by engine on lane `gpu`, then `book_metrics` on lane `cpu`; a chapter job that ends in `error` after its retries does not stop the others; when all are `done` or `error` and any is `error`, the run goes to `needs_attention` without `book_metrics`, and `wait` returns with the failed chapters and errors (FR-056)
- [ ] T070 [US1] Implement run doors in `app/api/v1/runs.py` with tools: `POST /books/{id}/runs`, `GET /runs/{id}`, `GET /runs/{id}/chapters`, `GET /runs/{id}/report`, `GET /runs/{id}/artifacts`, `GET /runs/{id}/artifacts/{aid}`, `GET /runs/{id}/bundle`, `GET /books/{id}/bundle`
- [ ] T071 [US1] Implement `POST /runs/{id}/chapters/{ord}/rerun` with `overrides` and tool `rerun_chapter`: new chapter artifacts only, `book_metrics` recomputed, report shows the override with `chapters: [ord]` (FR-044)
- [ ] T072 [P] [US1] Write `scripts/check_links.py`: count broken links and unreferenced files in a bundle directory

**Checkpoint**: MVP. A book goes in, a measured bundle comes out.

---

## Phase 5: User Story 2 - Every stage leaves an artifact and a broken run resumes (Priority: P2)

**Goal**: every stage is on disk, runs are append-only, an interrupted run resumes from the last
finished stage or chapter, and space can be reclaimed on request.

**Independent Test**: kill the worker mid-chapter on a long book, resume, compare with an
uninterrupted run (quickstart.md step 5).

### Tests for User Story 2

- [ ] T073 [P] [US2] Create `tests/stand/test_kill_resume.py`: kill the worker during a chapter, `POST /runs/{id}/resume`; finished chapters keep artifact sha, only the interrupted chapter reruns, the bundle is byte-identical to an uninterrupted run (SC-005)
- [ ] T074 [P] [US2] Create `tests/stages/test_resume_reuse.py`: a finished stage is reused only when its input hash is unchanged; a changed profile or engine build redoes that stage and every later one; a new run never touches an earlier run directory (FR-023, FR-025)
- [ ] T075 [P] [US2] Create `tests/doors/test_cleanup.py`: `DELETE /runs/{id}` of the result run moves the result to the next best run; `POST /cleanup` with `dry_run` lists only heavy artifacts of non-result runs and dropped candidates and never reports, profiles, measurements, model calls or result bundles

### Implementation for User Story 2

- [ ] T076 [US2] Make every stage look up `find_done` before working and skip on a hit, in `app/stages/intake.py`, `app/stages/metadata/resolve.py`, `app/stages/toc/reconcile.py`, `app/stages/assemble.py`, `app/stages/book_metrics.py` (FR-023)
- [ ] T077 [US2] Implement `POST /runs/{id}/resume` and `POST /runs/{id}/cancel` in `app/api/v1/runs.py` with tools; resume enqueues only chapters not `done`, including failed chapters of a `needs_attention` run (FR-046, FR-056); cancel checked between chapters and between engine page ranges
- [ ] T078 [US2] Check in `app/stages/assemble.py` that every artifact listed in User Story 2 scenario 1 is written: probes, toc per source and reconciled, engine output per page range, model after each rule, writer output, metrics
- [ ] T079 [US2] Implement `DELETE /runs/{id}` (run and its artifacts, result moves to the next best run) and `POST /cleanup` (`dry_run`, heavy artifacts of non-result runs and dropped candidates, `removed_at` set, rows kept) in `app/use_cases/cleanup.py` and `app/api/v1/runs.py` with tools `delete_run`, `cleanup` (FR-025)

**Checkpoint**: runs survive kills and restarts; disk can be reclaimed safely.

---

## Phase 6: User Story 3 - The stand assembles the book's profile (Priority: P3)

**Goal**: the stand probes a book, picks a preset, searches knob values on sampled chapters, and
keeps the best profile with evidence for every value.

**Independent Test**: two books with different layouts get different profiles in the knobs the
probes flagged; each value names the measurement that chose it; each report is no worse than the
same book on its preset alone.

### Tests for User Story 3

- [ ] T080 [P] [US3] Create `tests/stages/test_profile_search.py`: probes choose a preset; candidates scored with the report's chapter checks; the kept profile is no worse than the preset on the sampled chapters; every candidate stored with decision and reason (FR-013, FR-021)
- [ ] T081 [P] [US3] Create `tests/doors/test_profiles.py`: `GET /knobs`, `GET /presets`, `GET /profiles/{id}`, `POST /profiles/{id}/derive` creating a new immutable profile with source `manual`, `GET /runs/{id}/candidates`

### Implementation for User Story 3

- [ ] T082 [US3] Write `db/migrations/20261005000003_profile_candidates.sql` for `profile_candidates` (`search_job_id`, `profile_values jsonb`, `sample_chapters int[]`, `scores jsonb`, `decision` in (`kept`, `dropped`), `reason`) and its table in `app/orm/catalogue.py`; regenerate `db/schema.sql`
- [ ] T083 [P] [US3] Fill `config/knobs.yaml` with the knob groups: toc sources and order, chapter title, section heading, code block, note or sidebar, table, caption, running head, images, engine per range, chunk page count, model provider per step, search budget; and `config/presets/*.yaml` (default, bookmarked text PDF, scan, picture-led book)
- [ ] T084 [P] [US3] Implement probes in `app/probes/`: `layout.py` (columns, monospace share, image share, font profile), `scan.py` (pages without a layer), `matter.py` (front and back matter), each returning the knobs worth searching and a preset hint
- [ ] T085 [US3] Implement `app/stages/profile_search.py`: run probes, pick a preset, sample chapters (first, longest, one with code, one with figures), coordinate search over flagged knobs within the budget knob, score with `app/quality/chapter.py`, store every candidate, freeze the best into a profile with evidence (research R10)
- [ ] T086 [US3] Register job `profile_search` before chapter assembly in `app/job_handlers/run.py` when the run asks for `search: true`
- [ ] T087 [US3] Implement doors with tools in `app/api/v1/profiles.py`: `GET /knobs`, `GET /presets`, `GET /profiles/{id}`, `POST /profiles/{id}/derive`, `GET /runs/{id}/candidates` (FR-015)

**Checkpoint**: each book gets its own measured profile without a human.

---

## Phase 7: User Story 4 - Evaluation set and gated shared changes (Priority: P4)

**Goal**: evaluation sets with modes, gates registered before runs, per-member comparison naming
every book that got worse and every unexpected change.

**Independent Test**: register a gate, run a baseline, change one shared option, run again; the
result lists worse members with reasons and unexpected changes (quickstart.md step 7).

### Tests for User Story 4

- [ ] T088 [P] [US4] Create `tests/stages/test_evaluation.py`: a gate registered after the run starts is refused; worse members listed with deltas and reasons; a member whose output changed although no changed rule fired is counted separately (FR-027, FR-028)
- [ ] T089 [P] [US4] Create `tests/stages/test_eval_modes.py`: `bookmarks_off` scores other toc sources against bookmarks (FR-029); `as_scan` ignores the text layer and scores recognised text against it (FR-049)

### Implementation for User Story 4

- [ ] T090 [US4] Write `db/migrations/20261005000004_evaluation.sql` for `evaluation_sets` (`name` unique), `evaluation_members` (`mode` in (`normal`, `bookmarks_off`, `as_scan`), `best_profile_id`, `expected_metadata jsonb` checked values per field), `gates` (`columns`, `tolerance`, `untouchable int[]`, `registered_at`), `evaluation_runs` (`baseline_id`, `rows`, `result`) and tables in `app/orm/evaluation.py`; regenerate `db/schema.sql`
- [ ] T091 [US4] Record rules fired per chapter in `app/stages/assemble.py` and `report.json` `knobs_applied`, so changes can be attributed per member
- [ ] T092 [US4] Implement `app/evaluation/sets.py` and `app/evaluation/modes.py` (`bookmarks_off`, `as_scan` as run options)
- [ ] T093 [US4] Implement `app/evaluation/compare.py`: per-member metric deltas against the baseline, worse members with reasons against gate tolerance, unexpected-change count, metadata correctness against `expected_metadata` (SC-010), gate passed or failed; update `best_profile_id` when a member beats it (SC-007, SC-008)
- [ ] T094 [US4] Register job `eval_run` in `app/job_handlers/evaluation.py` and doors with tools in `app/api/v1/eval.py`: `POST /eval/sets`, `GET /eval/sets/{id}`, `POST /eval/gates`, `POST /eval/runs`, `GET /eval/runs/{id}`
- [ ] T095 [US4] Create the first evaluation set from research R15 (22 bookmark books, three scans, dannyh, two text books as scans) with `scripts/seed_eval_set.py`, filling `expected_metadata` from the title pages checked by the owner; owner adds a novel, a children's book, a school textbook and a poetry collection before the first run

**Checkpoint**: shared changes are judged on the whole set before they become defaults.

---

## Phase 8: User Story 5 - An external agent grows the knob registry (Priority: P5)

**Goal**: an external developer agent can find a defect, add a knob, and prove it changes nothing
for books that do not select it, using only doors and code.

**Independent Test**: add a knob for a known defect on one book; its report improves and the
evaluation set shows no change on members that do not select it.

### Tests for User Story 5

- [ ] T096 [P] [US5] Create `tests/stages/test_new_knob_isolation.py`: a dummy option registered but selected by no profile leaves every bundle byte-identical (FR-016)

### Implementation for User Story 5

- [ ] T097 [US5] Extend `GET /knobs` in `app/api/v1/profiles.py` with each option's implementation name and the probe, and add `POST /eval/runs` option `members` to run a subset (doors for the agent loop)
- [ ] T098 [US5] Validate `config/knobs.yaml` at start in `app/knobs/registry.py`: every option bound to a registered function, every knob with `help` and `probe`, a clear error naming the bad entry
- [ ] T099 [US5] Add a section "Adding a knob" to `README.md`: where options live, how to register, how to prove isolation with an evaluation subset run
- [ ] T100 [US5] Acceptance: through MCP only, add one real knob for a defect from the starting list (rag-lab-intake findings), show the improved report and the isolation run; record the result in `~/working_docs/projects/ocr-lab/notes/`

**Checkpoint**: the registry grows through doors and code, with proof.

---

## Phase 9: Polish & Cross-Cutting Concerns

- [ ] T101 [P] Write `README.md`: what the stand does, `docker compose --profile convert up`, doors, bundle layout, the GPU sharing rule with rag-lab
- [ ] T102 Run every step of `specs/001-pdf-book-to-markdown/quickstart.md` on the stand and fix what fails
- [ ] T103 [P] Record seconds and GPU seconds per stage and chapter in `report.json` `seconds` and check they are filled for the whole evaluation set (research R14)
- [ ] T104 Run `scripts/check.sh` clean and the house rules test before the first commit of each phase

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: none
- **Foundational (Phase 2)**: after Setup; blocks every story
- **US0 (Phase 3)**: after Foundational
- **US1 (Phase 4)**: after US0 (needs catalogue records and metadata versions)
- **US2 (Phase 5)**: after US1 (resumes the stages US1 builds)
- **US3 (Phase 6)**: after US1; best after US2, since search multiplies run time
- **US4 (Phase 7)**: after US1; uses US3 profiles for `best_profile_id`
- **US5 (Phase 8)**: after US4 (isolation is proven with evaluation runs)
- **Polish**: after the stories in scope

### Within Each User Story

- Tests are written first and fail before the implementation
- Migrations and tables before stages, stages before job handlers, handlers before doors
- Every door ships with its MCP tool in the same task (the parity test enforces it)

### Parallel Opportunities

- Setup: T003, T005, T006, T007, T008
- Foundational: T011 and T012; T015, T018, T020, T021; tests T022 to T024
- US0: tests T025 to T027; sources T030 to T034
- US1: tests T041 to T045; toc sources T046 to T051; T058, T059, T061, T062, T063, T065, T066, T067, T072
- US2: tests T073 to T075
- US3: T083 and T084
- US4: tests T088 and T089

---

## Parallel Example: User Story 1

```bash
# Toc sources, one file each:
Task: "Implement toc source app/stages/toc/sources/bookmarks.py"
Task: "Implement toc source app/stages/toc/sources/printed_contents.py"
Task: "Implement toc source app/stages/toc/sources/numbering.py"
Task: "Implement toc source app/stages/toc/sources/typography.py"

# Engine adapters and writer:
Task: "Implement app/engines/docling_adapter.py"
Task: "Implement app/engines/mineru_adapter.py"
Task: "Implement app/writers/markdown.py"
```

---

## Implementation Strategy

### MVP First

1. Phase 1 Setup, Phase 2 Foundational
2. Phase 3 US0: books in the catalogue with complete metadata
3. Phase 4 US1: measured bundle from the default preset
4. **Stop and validate** with quickstart.md steps 1 to 4 and 6

### Incremental Delivery

1. US2 makes long runs safe to interrupt
2. US3 adds per-book profiles
3. US4 adds the evaluation set and gates; non-technical books join before its first run
4. US5 opens the loop for an external agent

Each phase ends runnable and measured, and is validated with the owner before the next one starts.
