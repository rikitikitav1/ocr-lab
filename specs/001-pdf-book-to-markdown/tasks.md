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
- [x] T004 Create `docker-compose.yml`: `postgres` (postgres:17, healthcheck `pg_isready`, volume `pg_data`), one-shot `dbmate` (2.34.1, `./db:/db`, `DBMATE_NO_DUMP_SCHEMA=true`), `api` (uvicorn `server:app` on 8100, bind mount `.:/app`), `worker` (`restart: unless-stopped`, host UID/GID), `converter-docling` and `converter-mineru` with `image: rag-lab-converter-docling` / `rag-lab-converter-mineru`, `pull_policy: never`, no compose profile so a plain `docker compose up` starts them, `init: true`, `stop_grace_period: 45s`, GPU anchor `x-gpu` (CDI `nvidia.com/gpu=all`), `ollama` using external volume `rag-lab_ollama_data`; read-only mounts `../rag-lab/datasets/inbox/books` as `/shelf/books`, `../rag-lab/datasets/converter_gold` as `/shelf/gold`; volume `./data:/data` (research R5); no HuggingFace cache mount, since the converter images carry their models and ollama has its own volume (FR-034)
- [x] T005 [P] Create `.env.example` with `DATABASE_URL`, `MODEL_PROVIDERS` (ollama URL, OpenAI-compatible cloud URL and key), `CPU_LANE_THREADS=4`, shelf paths (research R12)
- [x] T006 [P] Configure ruff in `pyproject.toml` (line-length 120, select E4/E5/E7/E9/F/I/B) and write `scripts/check.sh` running `ruff check`, then `pytest -n 8`
- [x] T007 [P] Create `tests/real_db.py` (scratch database per module `CREATE DATABASE ocrtest_<uuid>` from `db/schema.sql` on `TEST_POSTGRES_URL`, skip when Postgres is unreachable) and `tests/conftest.py` with a FastAPI `TestClient` fixture (research R13)
- [x] T008 [P] Create `tests/repo/test_house_rules.py`: code comments carry no commit references, no plan section or arc numbers, no dates, no emoji (reopened by T128)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: catalogue tables, queue, artifacts, doors skeleton, engines, model client. No user
story starts before this phase is done.

- [x] T009 Write `db/migrations/20261009000001_init.sql` for `books` (`sha256 text unique`: hash of the ordered file sha256 list; `pages`, `text_layer jsonb`, `has_bookmarks`, `has_printed_contents`, `toc_sources jsonb`, `stage`, `result_run_id`), `book_files` (unique `(book_id, ord)`, `first_page`), `metadata_versions` and `toc_versions` (`version`, `input_hash`, `job_id`, `current bool`, one current per book and kind), `metadata_fields` (unique `(metadata_version_id, name)`, `value jsonb` null when unknown, `source`, `confidence real`, `attempts jsonb`), `toc_entries` (`level` 1..6, `level_source`, `kind`, `votes jsonb`), `profiles` (immutable, `values jsonb`, `chapter_overrides jsonb`, `sha256`, `parent_id`), `runs` (`metadata_version_id`, `toc_version_id`, `status`, `stage`, `code_hash`, `engine_builds jsonb`, `bundle_dir`), `chapters` (unique `(run_id, ord)`), `artifacts` (exactly one owner: `run_id` or a version id; `sha256`, `input_hash`, `heavy bool`, `removed_at`), `model_calls` (`request_hash` pk) as in data-model.md; regenerate `db/schema.sql`
- [x] T010 Write `db/migrations/20261009000001_init.sql` for `jobs` (`type`, `lane` in (`gpu`, `cpu`), `parent_id`, `run_id`, `options jsonb`, `status` in (`new`, `running`, `done`, `error`, `paused`, `cancelled`), `attempts`, `apply_since`, `waiting_because`, `code_hash`, `result`, `error`, `elapsed`) with an index for claiming; regenerate `db/schema.sql`
- [x] T011 [P] Create SQLAlchemy tables for the catalogue in `app/orm/catalogue.py` and the session factory in `app/orm/db.py`
- [x] T012 [P] Create SQLAlchemy table for jobs in `app/orm/jobs.py`
- [x] T013 Implement `app/artifacts.py`: write to a `.tmp` sibling, fsync, rename, then insert the manifest row; `input_hash(inputs, profile_sha, engine_builds)`; `find_done(owner, stage, chapter, name, input_hash)` returns a row only if the file exists and its sha matches; paths `data/books/<book_id>/<metadata|toc>/v<N>/` and `data/runs/<book_id>/<run_id>/<stage>/[<chapter>/]` (research R3, FR-020, FR-022) (reopened by T105)
- [x] T014 Implement `app/job_queue.py`: `enqueue` (validated by `app/job_specs.py`), `claim_next(lane)` with `FOR UPDATE SKIP LOCKED`, `reschedule` (backoff `60*attempts` s, attempt budget per job type read from `config/budgets.yaml`, 3 to 5, FR-057), `Deferred` (no attempt counted, up to 3600 s) and `Final`, `requeue_stale`, `cancel`/`pause`/`resume`, `pg_notify('job_changed', ...)` on every state change, `wait(job_id, timeout)` returning when the job and all its children are finished (research R4)
- [x] T015 [P] Create `config/budgets.yaml` (attempts per stage: `intake`, `metadata`, `toc`, `profile_search`, `assemble_chapter`, `book_metrics`, `eval_run`, each 3 to 5, validated at start) and `app/job_specs.py`: pydantic option specs and lane per job type (`book_run`, `intake`, `metadata`, `toc`, `profile_search`, `assemble_chapter`, `book_metrics`, `eval_run`, `cleanup`)
- [x] T016 Implement `app/worker.py`: one serial thread for lane `gpu`, `CPU_LANE_THREADS` threads for lane `cpu`, handler registry `@register`, hash of its own copy of `app/` and `config/` stamped on every claimed job, a restart onto newer code once the queue is empty, reported by the stand door (research R4)
- [x] T017 Implement `app/server.py` (FastAPI, routers under `/v1`, FastMCP server mounted at `/mcp` with stateless HTTP and chained lifespan) and `app/mcp_tools.py` with a helper that registers a tool for a use case function (FR-047)
- [x] T018 [P] Implement jobs doors in `app/api/v1/jobs.py` and their tools: `GET /jobs`, `GET /jobs/{id}`, `GET /jobs/{id}/wait`, `POST /jobs/pause|resume|cancel`, `GET /queue` (contracts/http_api.md, contracts/mcp_tools.md) (reopened by T115, T117, T133)
- [x] T019 Copy rag-lab engines into `app/engines/` (`converter.py` with `take_once`, `let_go`, `reading`; `converter_tools.py` for docling-serve and MinerU HTTP APIs; `card.py` with `hand_to`; `stamps.py`) and adapt: calls take an explicit file page range, every reading returns the engine build stamp from `GET /supervisor` and fails without one (research R7a, plan.md Constitution Check) (reopened by T116)
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
- [x] T027 [P] [US0] Create `tests/doors/test_books.py`: `POST /books` returns 201 then 200 for the same files; `PATCH /books/{id}/metadata/{name}` creates a new metadata version with source `manual` and keeps found values in evidence; `GET /books?series=` sorts by volume (reopened by T117)

### Implementation for User Story 0

- [x] T028 [US0] Implement `app/stages/intake.py`: store each file under `data/files/<sha[:2]>/<sha>.pdf`, compute book identity from the ordered file hashes, fill `book_files` with `first_page`, read pages, per-page text layer and bookmarks presence with pypdfium2, probe printed contents with the dot-leader parser ported from rag-lab `route.contents_outline`, write intake artifacts (FR-036, FR-054) (reopened by T105, T126) (FR-040)
- [x] T029 [US0] Implement `app/use_cases/books.py` (`add_book` from uploaded files or shelf paths, `list_books` with `stage`, `q`, `series` filters, `get_book`) and doors `POST /books`, `GET /books`, `GET /books/{id}` in `app/api/v1/books.py` with tools `add_book`, `books`, `book` (reopened by T115, T117, T125)
- [x] T030 [P] [US0] Implement metadata source `app/stages/metadata/file_metadata.py` (PDF info dictionary and XMP of every file) (reopened by T122)
- [x] T031 [P] [US0] Implement metadata source `app/stages/metadata/title_pages.py`: text of the first and last 20 pages (book knob `metadata.title_pages`, T040) (recognised text for pages without a layer, through a `gpu` lane reading of those pages only), ISBN by regex with checksum (a 10-digit one only next to an `ISBN` label), `original_isbn` for translations, year, publisher, edition, series and volume by per-language patterns; junk PDF metadata (`*.dvi`, `Microsoft Word - `, the file name) ignored
- [x] T032 [P] [US0] Implement metadata source `app/stages/metadata/catalogues.py`: Open Library (English) and Labirint (Russian) by ISBN then by title and author, Google Books when `GOOGLE_BOOKS_API_KEY` is set; each lookup recorded as an attempt with outcome `found`, `absent`, `conflict` or `failed` (reopened by T108) (removed with every outside metadata source: owner's decision of 2026-10-09)
- [x] T033 [P] [US0] Implement `app/stages/metadata/model_reader.py` (stand model reads title and copyright pages for fields still missing or in conflict, JSON output) and its `subject()` step, called from `resolve.py` `_subject`, for the free subject label ("databases, textbook" or "detective novel")
- [x] T034 [P] [US0] Implement `app/stages/metadata/language.py` with lingua over body text, per-language share for mixed books
- [x] T035 [US0] Implement `app/stages/metadata/resolve.py`: run every source for every field before giving up, fixed source priority per field, write a new `metadata_versions` row with `input_hash` of metadata knobs and source code hash, never guess a value (FR-037, FR-038, FR-052) (reopened by T105, T124)
- [x] T036 [US0] Register job handlers `intake` and `metadata` in `app/job_handlers/book.py`, chained after `POST /books`; `toc` joins this chain and the book reaches stage `ready` with T053; book stage moves `uploaded → metadata → toc → ready`
- [x] T037 [US0] Implement manual metadata edit in `app/use_cases/metadata.py` and door `PATCH /books/{id}/metadata/{name}` with tool `set_metadata`: new version, source `manual`, found values kept in evidence (FR-051)
- [x] T038 [US0] Implement `GET /books/{id}/metadata` and `POST /books/{id}/recollect` (`{"what": ["metadata", "toc"]}`) with tools; recollection also triggers when the stored `input_hash` no longer matches current knobs and source code (FR-052) (reopened by T106)
- [x] T039 [US0] Create `tests/stand/test_compose_smoke.py` (marked `stand`): `docker compose up` pulls no image, `/v1/stand` shows both converter build stamps (SC-009)
- [x] T040 [US0] Book-level knobs (FR-059): `books.knobs` column, `app/book_knobs.py` with defaults from `config/metadata.yaml` (title-page window 20 and 20), knobs at submission and `PATCH /v1/books/{id}/knobs` with tool `set_book_knobs`, printed contents pages given by hand recorded at intake (tests in `tests/doors/test_books.py`)

P0 also built, without a task of its own: the outside-call wrapper `app/net.py` with `config/net.yaml` and the `outside_hosts` table, web metadata sources `app/stages/metadata/web.py` with `config/web_sources.yaml` and `config/searxng/`, the field list in `app/stages/metadata/candidates.py`, `config/models.yaml`, `config/isbn_groups.yaml`, migrations `20261009000001_init.sql` and `20261009000001_init.sql`, and the doors `GET /metadata/coverage`, `POST /books/recollect`, `POST /jobs/retry`, `POST /books/upload` (plan.md Project Structure).

**Checkpoint**: books enter the catalogue with complete metadata through REST and MCP.

---

## Phase 4: User Story 1 - Feed a PDF, get a measured Markdown bundle (Priority: P1) 🎯 MVP

**Goal**: a catalogued book becomes a bundle (Markdown, `images/`, `profile.yaml`, `report.json`,
`report.md`) assembled chapter by chapter from a reconciled table of contents, with its numbers.

**Independent Test**: convert a PDF with bookmarks; chapters in the document match the bookmarks,
every image link resolves after moving the bundle, the report carries the numbers with the worst chapters named;
rerun one chapter with an override (quickstart.md steps 3, 4, 6).

### Tests for User Story 1

- [x] T041 [P] [US1] Create `tests/unit/test_reconcile.py`: entries matched across sources by normalised title and page, printed page offset resolved, level from the highest-ranked source with that source stamped, front and back matter kept with their `kind` (reconciliation is covered in `tests/stages/test_toc.py`; the file named here is not written) (tests/unit/test_reconcile.py; through collect in tests/stages/test_toc.py; back matter is the service role)
- [x] T042 [P] [US1] Create `tests/unit/test_document_model.py`: headings outside 1..6 rejected; chapter inner levels relative to the chapter level (FR-004, FR-043) (tests/unit/test_document_model.py: test_a_heading_level_outside_the_range_is_refused; levels 1..5 below the chapter per T058)
- [x] T043 [P] [US1] Create `tests/unit/test_markdown_writer.py`: title `#`, chapters `##` or parts `##` with chapters `###`; notes as `> **Note:**` blockquotes; ordered, unordered and nested lists keep their type (FR-005); chapter marker comments; relative image links (tests/unit/test_markdown_writer.py: test_title_chapters_parts_and_inner_headings_take_their_levels, test_notes_are_quotes_and_prose_never_turns_into_syntax, test_lists_keep_their_type_and_nesting)
- [x] T044 [P] [US1] Book numbers name the chapters found below their own sections, and the extra_text sum is asserted in tests/unit/test_quality.py (FR-019, FR-045); sums, failed and worst chapters are tested there already · chapters_below_sections and the extra_text sum, tests/unit/test_quality.py
- [x] T045 [P] [US1] Create `tests/stages/test_bundle.py`: `report.json` matches contracts/bundle.md schema 2; `scripts/check_links.py` finds zero broken links and zero unreferenced images after moving the bundle (SC-004); a fixture book with no code, formulas, verse or pictures gets the same report fields and link guarantees under the default preset (FR-050) (tests/doors/test_bundle.py: report.json against the contract's schema, check_links on a moved bundle, a plain book on the default preset)

### Implementation for User Story 1

- [x] T046 [P] [US1] Implement toc source `app/stages/toc/sources/bookmarks.py`: outline of each file placed under the file's position (FR-054)
- [x] T047 [P] [US1] Implement toc source `app/stages/toc/sources/printed_contents.py`: dot-leader parser reusing `intake.DOT_LEADER`, contents pages taken from book knob `toc.contents_pages` when set, plus the stand model reading contents pages without dot leaders (FR-059) (the model reader for contents without leaders is wired but unmeasured; a scan's contents window is recognised by MinerU in job `toc_scan`)
- [x] T048 [P] [US1] Implement toc source `app/stages/toc/sources/numbering.py` (PART, CHAPTER, ГЛАВА, Roman and dotted decimal grammar) (written in `numbering.py`; votes in reconciliation, never adds an entry alone)
- [x] T049 [P] [US1] Implement toc source `app/stages/toc/sources/typography.py`: whole-book style profile ported from `book_levels_proto.py` (body size is the mode, styles with fewer than 10 items merge into the nearest common one, text on 20+ pages is a running head, level = rank + 1 clamped to 6) (a later source: owner's decision of 2026-10-09, see research R9) (dropped from this feature: typography is a later source (research R9, revised 2026-10-09); not built)
- [x] T050 [P] [US1] Deferred while FR-037 keeps outside sources off: implement toc source `app/stages/toc/sources/catalogue.py` (Open Library `table_of_contents`, publisher pages) (a later source: owner's decision of 2026-10-09, see research R9) (dropped: no outside sources at this stage, owner's decision of 2026-10-09) (dropped from this feature: outside sources removed by T143 (FR-037); catalogues are a later source in R9)
- [x] T051 [P] [US1] Implement toc source `app/stages/toc/sources/model_levels.py`: the stand model assigns levels over the list of heading candidates, used last (a later source: owner's decision of 2026-10-09, see research R9) (dropped from this feature: the model over heading candidates is a later source (research R9, revised 2026-10-09); not built)
- [x] T052 [US1] Implement `app/stages/toc/reconcile.py` (rapidfuzz title match, page offset maximising matches, per-entry level from the highest-ranked source, `votes`) and `app/stages/toc/filter.py` (kinds `chapter`, `part`, `section`, `front_matter`, `back_matter`); write a new `toc_versions` row whose `input_hash` covers the `toc.*` book knobs plus a code hash of `app/stages/toc/`, and per-source artifacts (FR-008, FR-009, FR-052) (base: the printed contents when the text confirms its pages, else bookmarks, else chapter files; levels from the bookmarks where an entry has one; numbering only votes; `filter.py` kinds are part, chapter and section for now)
- [x] T053 [US1] Register job handler `toc` in `app/job_handlers/book.py` and door `GET /books/{id}/toc` (`source`, `version`) with tool `toc`; a run on a book with no toc version yet is refused with the reason (`start_run`), and one on a stale toc waits for the fresh one; add `toc` to `BUILT_BOOK_STAGES` in `app/job_specs.py`, set book stage `ready` after toc, and flip `test_recollect_refuses_toc_until_that_stage_exists` in `tests/doors/test_books.py` (FR-039, FR-041, FR-052) (submission takes `then` to chain `toc` without metadata; `book_run` enqueuing `toc` comes with T069)
- [x] T054 [P] [US1] HiPS PDFs and `GT_TOCs` at a pinned commit into `data/gold/hips/<commit>/` (CC BY-NC data, never committed), fetched by `toc_eval` with set `hips` rather than a job of its own (`app/evaluation/hips.py`; 48 scoreable books; LongDocBench moved to T146)
- [x] T055 [US1] Score a toc version against a gold TOC: chapters on the right page at any level, extra chapters against every gold level, entry recall and precision, level agreement (`app/evaluation/toc_gold.py`; no tree similarity, see T145)
- [x] T056 [US1] Register job `toc_eval` (spec in `app/job_specs.py`, budget in `config/budgets.yaml`) and door `POST /v1/eval/toc` with tool `toc_eval` per contracts/http_api.md and contracts/mcp_tools.md (`set`: `hips`, `longdocbench`, `bookmarks_off` over shelf books with bookmarks): runs intake and toc on each book, writes per-book scores and a summary artifact; works before chapter assembly exists. The `bookmarks_off` set applies the `bookmarks_off` mode created here in `app/evaluation/modes.py`, the one implementation that evaluation members reuse (T092, FR-029, FR-058) (`bookmarks_off` built; `hips` and `longdocbench` refused until T054)
- [x] T057 [P] [US1] `tests/unit/test_toc_gold.py` covers recall, precision, levels, chapters below the top, front matter not counted and a top entry the gold lists deeper (no TEDS, see T145)
- [x] T058 [P] [US1] Document model in `app/document/model.py`: heading (`level` 1..5 below the chapter's own heading, `level_source`), paragraph, code, table with spanned cells, list, figure, caption, note, footnote, formula, page marker with `(book page, file ord, in-file page)` (`tests/unit/test_document_model.py`) (FR-030)
- [x] T059 [P] [US1] Settle the default preset's genre question (owner's decision): code passes stay on, selecting themselves by the page's face, and FR-050 is reworded, or they move off by default; registry options name their implementing pass. Registry, presets and GET /v1/knobs are built (tests/unit/test_knobs.py) · owner, 2026-10-11: code passes only on technical books, T173
- [x] T060 [US1] Implement `app/profiles.py`: resolve preset plus overrides into an immutable profile with `sha256`, every value with `source` and `evidence`; `chapter_overrides`; `derive` (FR-012, FR-014)
- [x] T061 [P] [US1] `app/engines/docling_adapter.py`: docling-serve `json_content` into the model in body order, running heads counted apart, unknown labels kept as prose and counted (`tests/unit/test_docling_adapter.py`; probes on books 3 and 4 lost nothing)
- [x] T062 [P] [US1] `app/engines/mineru_adapter.py`: MinerU `docvortex.middle` into the model page by page, a paragraph broken by the page joined, HTML tables with spans (`tests/unit/test_mineru_adapter.py`; 13 cached chunks and probes on books 3 and 4, no unknown type; the `list` shape is unseen so far)
- [ ] T063 [US1] After T147, passes in app/assembly/passes.py for duplicate pages, decorative images (decorative.min_pages in config/quality.yaml) and sidebars kept as notes, each measured before it is on; running heads, captions and code passes are built
- [ ] T064 [US1] The recognition engine is a profile knob (FR-033; SCAN_ENGINE is a straw man) and long chapter ranges are read in chunks of a knob page count with continuation marked; the chapter assembly itself is built (both engines per chapter, owner's decision of 2026-10-10)
- [x] T065 [P] [US1] Implement chapter checks in `app/quality/chapter.py` as numbers: text lost against the layer and text not in it (running heads the engines set aside left out, picture pages left out), toc sub-entries found, long and empty headings, figures without an image file (FR-019) (`tests/unit/test_quality.py`; book 38: 2-3% lost on ordinary chapters)
- [ ] T066 [P] [US1] Scanned ranges report a wordfreq dictionary share and engine confidence where given, per page range, in report.json `scans` (FR-032); engines' agreement per page, chapter and book is built · dictionary_share per chapter and book (null for spaceless languages), measurement.md; engine confidence per range not yet
- [x] T067 [P] [US1] `app/writers/markdown.py`: levels with `LevelTooDeep` past 6, fences longer than any inside, pipe tables or HTML for spans, notes as blockquotes, footnotes, chapter marker comments (`tests/unit/test_markdown_writer.py`; relative image links wait for T064 to save images)
- [ ] T068 [US1] report.json carries pages as (file ord, in-file page) per range, the `scans` block and `knobs_tried` (FR-032, FR-054); book numbers, worst chapters, duplicates, the bundle and the result run are built · pages per file done (chapters[].files); scans and knobs_tried wait for T066 and the profile search
- [x] T069 [US1] The report records a skipped profile search, and wait_job on an attention run returns its failed chapters with their errors (test in tests/doors/test_runs.py); run orchestration is built · report.json profile_search, wait_job failed_chapters; tests/doors/test_runs.py
- [x] T070 [US1] Implement run doors in `app/api/v1/runs.py` with tools: `POST /books/{id}/runs`, `GET /runs/{id}`, `GET /runs/{id}/chapters`, `GET /runs/{id}/report`, `GET /runs/{id}/artifacts`, `GET /runs/{id}/artifacts/{aid}`, `GET /runs/{id}/bundle`, `GET /books/{id}/bundle` (built: start, run, chapters, report, artifacts; bundle doors wait) (bundle as tar for REST and as a file listing for MCP; `tests/doors/test_runs.py`)
- [x] T071 [US1] Implement `POST /runs/{id}/chapters/{ord}/rerun` with `overrides` and tool `rerun_chapter`: new chapter artifacts only, `book_metrics` recomputed, report shows the override with `chapters: [ord]` (FR-044) (overrides refused until the knob registry exists; `tests/doors/test_runs.py`)
- [x] T072 [P] [US1] Write `scripts/check_links.py`: count broken links and unreferenced files in a bundle directory (FR-003) (`tests/unit/test_check_links.py`; book 38 bundle moved: 18 links, none broken)

**Checkpoint**: MVP. A book goes in, a measured bundle comes out.

---

## Phase 5: User Story 2 - Every stage leaves an artifact and a broken run resumes (Priority: P2)

**Goal**: every stage is on disk, runs are append-only, an interrupted run resumes from the last
finished stage or chapter, and space can be reclaimed on request.

**Independent Test**: kill the worker mid-chapter on a long book, resume, compare with an
uninterrupted run (quickstart.md step 5).

### Tests for User Story 2

- [ ] T073 [P] [US2] Create `tests/stand/test_kill_resume.py`: kill the worker during a chapter, `POST /runs/{id}/resume`; finished chapters keep artifact sha, only the interrupted chapter reruns, the bundle is byte-identical to an uninterrupted run (SC-005) (FR-024)
- [ ] T074 [P] [US2] Create `tests/stages/test_resume_reuse.py`: a finished stage is reused only when its input hash is unchanged; a changed profile or engine build redoes that stage and every later one; a new run never touches an earlier run directory; a write that fails on a full disk leaves no manifest row and the stage reruns on resume (FR-022, FR-023, FR-025)
- [ ] T075 [P] [US2] Create `tests/doors/test_cleanup.py`: `DELETE /runs/{id}` of the result run moves the result to the next best run; `POST /cleanup` with `dry_run` lists only heavy artifacts of non-result runs and dropped candidates and never reports, profiles, measurements, model calls or result bundles

### Implementation for User Story 2

- [ ] T076 [US2] Make every stage look up `find_done` before working and skip on a hit, in `app/stages/intake.py`, `app/stages/metadata/resolve.py`, `app/stages/toc/reconcile.py`, `app/stages/assemble.py`, `app/stages/book_metrics.py` (FR-023)
- [x] T077 [US2] Implement `POST /runs/{id}/resume` and `POST /runs/{id}/cancel` in `app/api/v1/runs.py` with tools; resume enqueues only chapters not `done`, including failed chapters of a `needs_attention` run (FR-046, FR-056); cancel checked between chapters and between engine page ranges (`app/stages/run_state.py`: resume restarts every chapter not done from kept readings; `tests/doors/test_runs.py`)
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

- [ ] T080 [P] [US3] Create `tests/stages/test_profile_search.py`: probes choose a preset; candidates scored with the report's chapter checks; the kept profile is no worse than the preset on the sampled chapters; every candidate stored with decision and reason; a search killed after some candidates and resumed scores only the rest (FR-013, FR-021, FR-023)
- [ ] T081 [P] [US3] Create `tests/doors/test_profiles.py`: `GET /knobs`, `GET /presets`, `GET /profiles/{id}`, `POST /profiles/{id}/derive` creating a new immutable profile with source `manual`, `GET /runs/{id}/candidates`; every value of a resolved profile names an artifact that opens through `GET /runs/{id}/artifacts/{aid}` (SC-006)

### Implementation for User Story 3

- [ ] T082 [US3] Write `db/migrations/20261009000002_profile_candidates.sql` for `profile_candidates` (`search_job_id`, `profile_values jsonb`, `sample_chapters int[]`, `scores jsonb`, `decision` in (`kept`, `dropped`), `reason`) and its table in `app/orm/catalogue.py`; regenerate `db/schema.sql`
- [ ] T083 [P] [US3] Fill `config/knobs.yaml` with the knob groups: toc sources and order, chapter title, section heading, code block, note or sidebar, table, caption, running head, verse (line breaks kept, dialogue dashes kept as text), tables and figures continued on the next page, images, engine per range, chunk page count, model provider per step, search budget (number of candidate profiles scored); and `config/presets/*.yaml` (default, bookmarked text PDF, scan, picture-led book)
- [ ] T084 [P] [US3] Implement probes in `app/probes/`: `layout.py` (columns, monospace share, image share, font profile), `scan.py` (pages without a layer), `matter.py` (front and back matter), each returning the knobs worth searching and a preset hint
- [ ] T085 [US3] Implement `app/stages/profile_search.py`: run probes, pick a preset, sample chapters (first, longest, one with code, one with figures), coordinate search over flagged knobs within the budget knob (candidates scored), score with `app/quality/chapter.py`, store every candidate, freeze the best into a profile with evidence (research R10)
- [ ] T134 [US3] Make profile search resumable in `app/stages/profile_search.py`: each scored candidate is written as an artifact with its input hash (book, profile values, sample chapters, engine builds, code hash) next to its `profile_candidates` row, and a resumed search finds them with `find_done` and scores only the rest (Constitution VIII, FR-021, FR-023)
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

- [ ] T090 [US4] Write `db/migrations/20261009000003_evaluation.sql` for `evaluation_sets` (`name` unique, `targets jsonb`: SC-002 and SC-011 targets, both 1.0), `evaluation_members` (`mode` in (`normal`, `bookmarks_off`, `as_scan`), `best_profile_id`, `expected_metadata jsonb` checked values per field), `gates` (`columns`, `tolerance`, `untouchable int[]`, `registered_at`), `evaluation_runs` (`baseline_id`, `rows`, `result`) and tables in `app/orm/evaluation.py`; regenerate `db/schema.sql`
- [ ] T091 [US4] Record rules fired per chapter in `app/stages/assemble.py` and `report.json` `knobs_applied`, so changes can be attributed per member
- [ ] T092 [US4] Implement `app/evaluation/sets.py` and add `as_scan` to `app/evaluation/modes.py` as a run option next to `bookmarks_off`, which T056 created and members reuse as is (FR-029, FR-049)
- [ ] T093 [US4] Implement `app/evaluation/compare.py`: per-member metric deltas against the baseline, worse members with reasons against gate tolerance, unexpected-change count, metadata correctness against `expected_metadata` seeded from `eval/gold/metadata.yaml` (SC-010), `chapter_below_own_section` and `max_level` per member (SC-003), registry size (knobs, options) and options added since the baseline (Development Workflow), gate passed or failed; update `best_profile_id` when a member beats it (SC-007, SC-008)
- [ ] T094 [US4] Register job `eval_run` in `app/job_handlers/evaluation.py` and doors with tools in `app/api/v1/eval.py`: `POST /eval/sets`, `GET /eval/sets/{id}`, `POST /eval/gates`, `POST /eval/runs`, `GET /eval/runs/{id}`
- [ ] T095 [US4] Create the first evaluation set from research R15 (22 bookmark books, three scans, dannyh, two text books as scans) with `scripts/seed_eval_set.py`, filling `expected_metadata` from `eval/gold/metadata.yaml` (books with `checked: true`, matched by sha256 prefix) (SC-010)
- [ ] T135 [US4] Owner's decision: the novel, children's book, school textbook and poetry collection that join the evaluation set before its first run, added through `scripts/seed_eval_set.py` (FR-050, research R15)

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
- [ ] T100 [US5] Acceptance: through MCP only, add one real knob for a defect from the starting list (rag-lab-intake findings), show the improved report and the isolation run; keep the trial eval runs and their results as stand artifacts and record the result, with links to them, in `~/working_docs/projects/ocr-lab/notes/` (Constitution VIII)

**Checkpoint**: the registry grows through doors and code, with proof.

---

## Phase 9: Polish & Cross-Cutting Concerns

- [ ] T101 [P] Update `README.md`, which exists since P0: what the stand does, `docker compose up`, doors, bundle layout, the GPU sharing rule with rag-lab (T099 adds its own section)
- [ ] T102 Run every step of `specs/001-pdf-book-to-markdown/quickstart.md` on the stand and fix what fails
- [ ] T103 [P] Record seconds and GPU seconds per stage and chapter in `report.json` `seconds` and check they are filled for the whole evaluation set (research R14)
- [ ] T104 Run `scripts/check.sh` clean and the house rules test before the first commit of each phase

FR-030 has no task here: this feature ships one format. When a second format arrives, a full evaluation-set run showing byte-identical Markdown bundles is its regression proof.

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
- **Convergence (Phase 10)**: each task runs with or after the task that creates its file: T106 with T069 (`app/job_handlers/run.py`), T109 with T068, T110 and T120 with T064, T118 with T055, T090 and T093, T131 with T068; T116 lands before T061 and T062 so the adapters get readings with build stamps; the rest edit files P0 built and can run now

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

## Phase 10: Convergence

**Purpose**: gaps found by `/speckit-converge` on 2026-10-09 after P0, most severe first. Severity and gap type per task:
`~/working_docs/projects/ocr-lab/reviews/2026-10-09_converge_findings.md`.

- [x] T105 Store the hashed input parts (files, rule, knobs, code hash, engine build) in `artifacts.meta.inputs` on every `write()` in `app/artifacts.py` and pass them from `app/stages/intake.py` and `app/stages/metadata/resolve.py` (Constitution VIII, FR-020)
- [x] T106 [US0] Recollect stale book-level versions: compare stored `input_hash` with the current one in `app/job_handlers/run.py` before a run, enqueue `metadata`/`toc` when they differ, and show `stale` per version in `app/use_cases/books.py` `_view` (FR-052) (the run defers until the stale versions are collected again; `stale` in the book view; `tests/doors/test_runs.py`)
- [x] T107 Route model provider calls in `app/models_client.py` through `app/net.py` (retries 0.1/0.5/1 s, set-aside shown on `/v1/stand`); leave the engine job-start POSTs in `app/engines/converter_tools.py` single, as FR-060 says (FR-060)
- [x] T108 [P] [US0] Take ISBN, publisher and year in `app/stages/metadata/catalogues.py` `_open_library_edition` only when exactly one distinct ISBN fits, else record `failed: ambiguous`; test in `tests/stages/test_metadata.py` (FR-037) (removed with `catalogues.py`)
- [x] T109 [US1] report.json `metadata` lists every field with its source and marks manual ones, and report.md shows them (FR-051, FR-052); versions are there already · report.json metadata.fields, report.md Metadata section; tests/doors/test_bundle.py
- [x] T110 [US1] Split chapter page ranges at file boundaries in `app/stages/assemble.py` before engine calls, keeping `(file ord, in-file page)` on page markers; test in `tests/stages/test_assemble_multifile.py`, including a book whose files mix a scan and a text file (FR-031, FR-054) (tests/stages/test_assemble.py: test_a_chapter_over_two_files_is_assembled_without_engines, test_a_chapter_s_ranges_split_where_pages_turn_from_layer_to_recognition)
- T111 merged into T047 and T052.
- T112 merged into T082 and T090.
- T113 merged into T059.
- [x] T114 [US0] Split the `metadata` job in `app/job_specs.py` and `app/job_handlers/book.py` by what each step needs: file, title-page text and cloud model steps on a `cpu` job; MinerU recognition and local model steps on a `gpu` child (FR-048) (`metadata` on the CPU lane hands itself to `metadata_gpu` when a step needs the card; 117 books recollected from cache in 76 s with no GPU child; `tests/doors/test_books.py`)
- [x] T115 [US0] Add a `book_id` filter to `GET /v1/jobs` and the `lane` and `book_id` arguments to tool `jobs` in `app/use_cases/jobs.py`, as contracts/http_api.md and contracts/mcp_tools.md list them, and per-stage status with the last error in `app/use_cases/books.py` `_view` (FR-041, FR-048) (`tests/doors/test_books.py`; stages under `stages` in the book view)
- [x] T116 Return the engine build stamp from every reading in `app/engines/converter_tools.py` and fail a reading without one (T019, Principle VII) (`converter_tools.stamped`: the stamp asked after the work, a changed build fails the reading; `tests/unit/test_converter.py`)
- [x] T117 [US0] Return 201/200 from `POST /v1/books`, 201 from `/books/upload`, 202 `{job}` from `POST /v1/books/{id}/recollect` in `app/api/v1/books.py`, assert them in `tests/doors/test_books.py`, and align `contracts/http_api.md` and `contracts/mcp_tools.md` (jobs `changed` shape, `metadata` tool) (`tests/doors/test_books.py`; recollect answers `202 {job_id}`, the contract says so)
- [ ] T118 [US4] SC-011 checked for scanned books, and compare.py reuses the toc_gold SC-002 check against evaluation_sets.targets (after T090); SC-002 is scored in app/evaluation/toc_gold.py
- T119 merged into T093 and T095.
- [x] T120 [US1] A test pins that a page listed in text_layer.garbled is read as recognition in assemble.ranges (FR-031); the code reads them so already (assemble.scanned_pages) (tests/stages/test_assemble.py: test_a_garbled_page_is_read_by_recognition_like_a_page_without_a_layer)
- T121 merged into T053.
- [x] T122 [P] [US0] Read XMP and every file's info dictionary in `app/stages/metadata/file_metadata.py` (T030) (`pdf.xmp`, readable in 65 of 117 books; `tests/stages/test_metadata.py`)
- [x] T123 Drop the HuggingFace cache mount from the plan: the app needs none, the converter images carry their models and ollama has its own volume (FR-035); plan and T004 text updated
- [x] T124 [US0] Hash only `metadata.*` knobs in `app/stages/metadata/resolve.py` `input_hash` (FR-052) (the metadata input hash takes only `metadata.*` knobs)
- [x] T125 [US0] Sort series volumes numerically, Roman numerals included, in `app/use_cases/books.py` `list_books` (FR-055)
- [x] T126 [US0] Record `(file ord, in-file page)` for every listed page in probe.json in `app/stages/intake.py` `_probe` (FR-054) (`where` in probe.json, `intake.located`; `tests/stages/test_intake.py`)
- [x] T127 [US0] Move per-language title-page phrases to `config/` tables read by `app/stages/metadata/title_pages.py` and `resolve.py` (spec Assumptions) (all language words now in `config/title_pages.yaml`; translation credits dropped by owner's decision of 2026-10-09)
- [x] T128 Shorten the two-line comments in `app/` to one line and add a comment-length check to `tests/repo/test_house_rules.py` (Constitution Development Workflow) (every comment one line, `test_a_comment_is_one_line`)
- [x] T129 [P] Move the tests in `tests/unit/test_review_fixes.py` into the test modules of their subjects and delete the file
- [x] T130 [P] Add `jobs.book_id`, `reclaims`, `deferred_seconds`, `updated_at`, `model_calls.provider` and table `outside_hosts` to `specs/001-pdf-book-to-markdown/data-model.md`, and keep its `jobs.type` list in step with `app/job_specs.py`
- [x] T131 [US1] Add `tests/unit/test_result_run.py` pinning the result-run order: least text lost, then most toc sub-entries found, then least text not in the layer, then latest (FR-053) (`app/stages/result_run.py`, recomputed after each book run)
- T132 merged into T054 and T056.
- [x] T133 Add the GPU holder to `job_queue.stats()` in `app/job_queue.py` for `GET /v1/queue` (T018) (added in the `queue` use case, `card.holders()`)

## Phase 11: P1 decisions of 2026-10-09

Built during the toc stage from the owner's decisions; the log is `~/working_docs/projects/ocr-lab/notes/toc_log.md`.

- [x] T136 A book without any contents is one chapter at most 100 pages, else the toc job waits with the reason (FR-061; `test_a_short_book_without_contents_is_one_chapter`, `test_a_long_book_without_contents_waits_for_attention`)
- [x] T137 `books.page_offset` holds the measured offset (migration `20261009000001_init.sql`, FR-062; `test_a_book_without_bookmarks_takes_its_printed_contents_and_stores_the_offset`)
- [x] T138 A scan's contents window is recognised by MinerU in job `toc_scan` on the GPU lane, cached per chunk (`app/stages/toc/scan.py`, FR-008; `test_a_scans_recognised_contents_become_entries_with_levels_and_an_offset`)
- [x] T139 Chapter files are a toc source and submissions take `order: "by_number"` (`app/stages/toc/sources/files.py`, `app/stages/file_order.py`, FR-054; ostep 63 files ordered 1-57, A-E)
- [x] T140 Book knob `toc.skip_root_bookmark` (FR-059; `test_the_root_bookmark_knob_lifts_the_chapters_to_the_top`)
- [x] T141 Text entering the stand is cleaned of invisible and control characters (`app/text_clean.py`; `tests/unit/test_text_clean.py`)
- [x] T142 Score the toc against bookmarks with bookmarks switched off on the shelf books that have them, chapters starting on the right page first, as job `toc_eval` (FR-058, SC-002; `temp_files/toc_vs_bookmarks.py` is the probe it replaces) (1677 of 1681 with bookmarks on; with them off, every chapter of the books that print a contents)
- [x] T143 Outside metadata sources removed (`catalogues.py`, `web.py`, SearXNG, `config/web_sources.yaml`, the `editions` field); every value comes from the book itself (FR-037, owner's decision of 2026-10-09; 7 of 140 values were lost on the first 15 books, all optional)
- [x] T144 Translators, illustrators, original year and original ISBN are no longer collected; the year of an edition comes from its edition history or catalogue card before the copyright line (FR-037; `test_the_edition_year_comes_before_the_copyright_year`, gold 120 of 120 fields)

## Phase 12: Chapter content, after the adapters

The owner's order for chapter content: model and writer, the two adapters, then a detection scheme per element measured before any rule.

- [x] T145 The toc is not scored by tree similarity: chapters on the right page and level agreement are enough (owner's decision, FR-058 and Clarifications)
- [ ] T146 LongDocBench link checked again; research R16 drops its fetch-script claim or the script is written (FR-058)
- [ ] T147 Schemes measured for formulas, running heads and images with captions, drawn like docs/diagrams/code.drawio.svg; code and tables are measured (elements_log 2-15)
- [ ] T148 Code from the text layer (knob assembly.code_from_layer, Docling code enrichment off) passes a gate run with no harm, or stays a knob; built and measured alone (elements_log 6); same owner's decision as T059
- [x] T149 Every chapter the shelf misses with bookmarks switched off (77 of 1918, job 4291) is explained in the toc log by class (toc_log s9) or found (SC-002) · toc_log s15, job 7406: 77 missed by class (service parts 26, gold noise 22, wrong chapters 10, wrong page 8, part pages 7, glued titles 4); real defects on 69, 75, 19, 101, 108, 65, offsets on 23, 8, 47, 109

## Phase 13: Convergence

- [x] T150 report chapters below their own sections and the max heading level per chapter and book in app/quality/chapter.py and app/quality/book.py, worst chapters named, in report.md and contracts/bundle.md, closing T044 per Constitution III (partial) · max_heading_level, headings_not_below_title, chapters_below_sections, worst deepest chapters, report.md row, contracts/bundle.md; tests/unit/test_quality.py
- [ ] T151 keep MinerU's all-caps boxes out of the headings as a book knob in app/assembly/passes.py, measured on book 9 (13 long headings) per Constitution IV (partial) · parked by the owner (no per-book knobs for now); measured offline: heading_max_words 12 turns 19 headings of book 9 into paragraphs, all boxed tasks, long_headings 13 to 0, lost and subs unchanged; patch kept outside the repo
- [x] T152 Count headings per level source per chapter and for the book in report.json and report.md from Heading.level_source per FR-009 (missing) · heading_sources per chapter and book, report.md row; tests/unit/test_quality.py
- [ ] T153 Add a toc_eval set of a seeded sample of about 50 ICDAR/INEX Book Structure Extraction 2013 books in app/evaluation/, scored by toc_gold and by the set's title-based and link-based scorers per FR-058 (missing)
- [ ] T154 Join letter-spaced rows when the measures read the layer in app/quality/chapter.py, bundle text unchanged, through a gate registered before the run (11, 26, 77, 63, 25 move; 23 untouched) per FR-045 (partial)
- [x] T155 Add a "text absent" column: the layer's running heads and folios found in the chapter, per chapter and book, in app/quality/chapter.py and app/quality/book.py per FR-045 (partial) · running_heads_in_text per chapter and book, report.md row; tests/unit/test_quality.py
- [x] T156 Make app/stages/result_run.py rank follow FR-053 (lost, most sub-entries found, least extra, latest) or record the owner's order in the spec, and update tests/unit/test_result_run.py per FR-053 (contradicts) · owner, 2026-10-11: the code's order with duplicates is the rule, FR-053 reworded
- [x] T157 Justify in the spec, or remove, the rule that only runs on the current toc version can be the book's result (result_run.recompute, collect clearing result_run_id) per FR-053 (unrequested) · owner, 2026-10-11: kept, FR-053 states it
- [ ] T158 Break a referee tie in app/assembly/referee.py per_page without favouring Docling by list order, gated on every text book with out_of_order as a column per FR-045 (partial)
- [ ] T159 Flag an engine page that comes back empty on an inked page, and try a pypdfium2 render of MRC pages as a book knob on book 9 per FR-031 (partial) · the pypdfium2 Docling backend measured worse in rag-lab as a text extractor (owner); here only the render of recognised (scan, garbled) ranges is at stake, or pages rendered by us and handed over as images, docling-parse kept on layer pages; after the rag-lab comparison, in own images
- [ ] T160 Tokenise CJK per character in the shared word reader (referee.WORD) used by agreement, the referee and the chapter measures, gated with every non-CJK book byte-identical per FR-032 (contradicts)
- [ ] T161 Count recognised pages where one engine is empty apart from disagreement in passes.recognised, and take Docling's text where MinerU is empty and Docling passes a sanity check, under its own gate per FR-032 (partial)
- [ ] T162 Build the hand-checked text gold of 20 to 30 pages from Russian scans on the shelf, checked by the owner, and score recognised text against it per FR-049 (missing)
- [x] T163 Stamp the toc version's base and voting sources in report.json per Constitution VII (partial) · report.json metadata.toc_sources (base, voting); tests/doors/test_bundle.py
- [x] T164 Reword the comments in app/stages/toc/collect.py and config/toc.yaml and rename test_a_long_book_without_contents_waits_for_attention so they say a long book without contents fails as structure not recognised per FR-061 (contradicts) · config/toc.yaml, collect.py header, test renamed
- [x] T165 Name the worst chapters by repeated_paragraphs and long_headings in app/quality/book.py and show worst out_of_order in report.md per FR-045 (partial) · worst repeated_paragraphs, long_headings and out_of_order named in report.json and report.md
- [x] T166 Add repeated_paragraphs, out_of_order, order_anchors, out_of_order_anchors and worst.out_of_order to the report schema in contracts/bundle.md per plan: contracts/bundle.md (partial) · repeated_paragraphs, out_of_order, order_anchors, out_of_order_anchors, heading_sources and the new worst lists in contracts/bundle.md; tests/doors/test_bundle.py
- [x] T167 Enqueue the toc when a run starts on a book without a current toc version, or drop that claim from T053, in app/use_cases/runs.py start_run per T053 (partial) · T053 reworded: start_run refuses a book without a toc, with the reason
- [x] T168 Put the run's profile id and sha256 into the chapter artifacts' inputs in app/job_handlers/run.py chapter_inputs per FR-020 (partial) · the run's profile id in the chapter inputs (a profile's values never change under its id)
- [x] T169 Always create images/ in the bundle, also when a book has no figures, in app/stages/bundle.py per FR-002 (partial) · images/ made for every bundle; tests/doors/test_bundle.py
- [x] T170 Add made_with to the FR-037 field list (owner's decision) or drop it from app/stages/metadata per FR-037 (unrequested) · owner, 2026-10-11: kept, FR-037 lists it as optional
- [x] T171 Reword the comments citing elements_log in config/assembly.yaml and "(owner's decision)" in app/stages/assemble.py and config/quality.yaml as plain reasons, and remove the orphan scan-engine comment in app/stages/assemble.py per Constitution Development Workflow (contradicts) · comments reworded in config/assembly.yaml, config/quality.yaml, app/stages/assemble.py; orphan comment gone
- [ ] T172 (after the non-invasive tasks) The intake probe reports the layer's defect signs as numbers in the book's text_layer, no verdict, backfilled for every book on the shelf and listed in docs/books.md: share of one- and two-letter words, share of letter-spaced rows, PDFium line breaks inside a word on one row, alphabet runs, page image kinds (JPEG, JBIG2, masked), made_with; seen on 110, 11, 8, 9 per FR-045 (missing)
- [ ] T173 Code passes move to a `technical` preset, off in the default: chosen from the layer's share of monospace text, or the metadata subject for a scan without a layer, overridable at submission; the default change goes through a gate (every non-technical book's bundle unchanged except code, every technical book picks the preset) per FR-050 (owner's decision of 2026-10-11)
- [x] T174 A submission can ask for a run once its toc is ready: `then` takes "run" beside "metadata" and "toc" (default without it), the upload door takes `then` too, the toc job starts the run on success and a book whose structure is not recognised gets none (owner, 2026-10-11) · then takes "run", the toc job starts it under itself so waiting on the intake waits for the book; tests/doors/test_runs.py
- [x] T175 The book view after intake (refined after the toc) and the start of a run give an ETA: the run's own time from its layer and scan pages times the shelf's seconds per page (median with the min-max spread, from the finished reports' `seconds`), and when it starts from the runs queued ahead on the card (owner, 2026-10-11) · app/stages/eta.py: cost per page from the stand's finished runs that really read (job time over pages), unknown until a kind has runs; in the book view and start_run; tests/unit/test_eta.py
- [x] T176 `book_bundle` and `bundle` answer with the report's numbers and a download link to the run's tar beside the bundle dir and files, so an agent reads the result and a person or curl fetches it; the link is not written into report.json (owner, 2026-10-11) · numbers and download (settings.STAND_URL) in bundle and book_bundle; tests/doors/test_runs.py
- [ ] T177 (later, not this MR) The toc stops depending on word lists in config/toc.yaml: a printed contents page is found by its shape (numbered lines whose page numbers rise and reach the book's end) with the heading word only a hint, and chapter labels are found as a word repeated at the top of many pages with a rising number; gated by a shelf toc snapshot, only books the lists missed may move (owner, 2026-10-11)
