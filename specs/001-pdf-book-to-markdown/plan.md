# Implementation Plan: PDF Book to Measured Markdown Bundle

**Branch**: `001-pdf-book-to-markdown` (P0, merged in PR #1); P1 on `002-p1-toc` | **Date**: 2026-10-05 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/001-pdf-book-to-markdown/spec.md`

## Summary

A stand under Docker Compose takes a PDF book (text or scanned), catalogues it with complete
metadata, builds a reconciled structure (a tree of nodes) from every source it can find, assembles a
per-book profile of knobs by mechanical probes and a sampled search, assembles the book piece
by piece through Docling or MinerU into its own document model, and writes a Markdown bundle
with images, the resolved profile and a quality report. Every stage writes atomic artifacts with a
manifest in Postgres, so any run resumes from the last finished stage or piece. Work goes
through a Postgres job queue with a serial GPU lane and a parallel CPU lane; everything is reachable
through an HTTP API and the same operations as MCP tools. Engines and model weights are the ones
rag-lab already holds. Decisions and their reasons: [research.md](research.md).

## Technical Context

**Language/Version**: Python 3.12, uv with a frozen lock

**Primary Dependencies**: FastAPI, uvicorn, fastmcp, SQLAlchemy 2 with psycopg, pydantic 2,
pypdfium2, rapidfuzz, lingua-language-detector, wordfreq, httpx, openai SDK (OpenAI-compatible
providers: ollama, DeepSeek and similar); engines Docling
(docling-serve 1.35.0) and MinerU 4.0.7 in the reused rag-lab images; reportlab for test fixtures

**Storage**: PostgreSQL 17 (catalogue, queue, manifests, evaluation); filesystem volume `data/`
for books, run artifacts and bundles; read-only mounts of the rag-lab shelf. No HuggingFace
cache mount: the converter images carry their models and ollama keeps its own volume

**Testing**: pytest with xdist, scratch database per module from `db/schema.sql`, FastAPI
TestClient and MCP client for doors, a kill-and-resume stand test; ruff

**Target Platform**: Linux host with one NVIDIA GPU (CDI), Docker Compose

**Project Type**: web service (API plus worker) with MCP tools, no frontend

**Performance Goals**: none fixed in this feature (spec); every stage and piece records seconds
and GPU seconds so targets can be set after the first evaluation run (research R14)

**Constraints**: one GPU shared with rag-lab, only one stand holds the converters at a time; no
image or model re-download (SC-009); model calls cached and reproducible; artifacts never
overwritten, removed only by an explicit cleanup

**Scale/Scope**: one owner; shelf of 135 PDFs in 34 folders plus 2074 gold PDFs; books up to
~1100 pages; first evaluation set about 25 books (research R15)

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| principle | how the plan meets it | status |
|---|---|---|
| I. Autonomous Conversion | one `POST /books/{id}/runs` produces the bundle; profile search runs inside the stand; failures still produce a bundle whose numbers show the loss | pass |
| II. Book Profile of Knobs | `config/knobs.yaml` registry, presets, immutable profiles with source and evidence per value, piece overrides | pass |
| III. Measured Quality | report schema in `contracts/bundle.md`; structure metrics are first-class; search scores with the report's own checks | pass |
| IV. Structure Matches the Book | structure stage reconciling bookmarks, printed contents (recognised on scans), chapter files and numbering, level source stamped per node, the structure's nodes as the unit, levels from the structure | pass for the levels, the tree in phase 14 |
| V. Format-Agnostic Core | own document model; engine adapters; Markdown writer reads only the model | pass |
| VI. Gated Shared Behaviour | evaluation sets, gates registered before runs, per-member deltas, unexpected-change count | pass |
| VII. Reproducible Runs | profile sha, engine build stamps, code hash on every run; model calls cached | pass |
| VIII. Artifacts and Resumable Runs | atomic write plus manifest row per artifact; resume by input hash; kill-and-resume test | pass |
| Technical Constraints | Python, Compose, models for narrow steps inside, external agent via MCP, local storage | pass |
| Output Contract | bundle layout and link rules in `contracts/bundle.md`, link checker in tests | pass |
| Development Workflow | evaluation set as regression; plain one-line comments; plans, notes and logs in `~/working_docs`, Spec Kit artifacts in `specs/<feature>/` as the constitution (1.1.2) allows | pass |

Post-design re-check (after `data-model.md` and `contracts/`): no change, all pass. Points to
watch during implementation:

- No genre is assumed (Principle II, FR-050): rules for code, formulas, verse and picture-led
  pages are knob options the default preset does not select. Keeping running heads, footers,
  sidebars and captions out of the headings is on for every book in the default preset
  (Principle IV, FR-006); a few non-technical books join the
  evaluation set before its first run (research R15).

- Principle VII with reused images: the images are built in rag-lab, so reproducibility rests on
  their build stamp being recorded per reading; a reading without a stamp fails the run.
- `rag-lab-intake/` moved to `~/working_docs/projects/ocr-lab/notes/` before git init (done).

## Project Structure

### Documentation (this feature)

```text
specs/001-pdf-book-to-markdown/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── http_api.md
│   ├── mcp_tools.md
│   └── bundle.md
├── checklists/requirements.md
└── tasks.md             # /speckit-tasks, not created here
```

### Source Code (repository root)

```text
app/
├── server.py                 # FastAPI app, mounts MCP at /mcp
├── mcp_tools.py              # one tool per use case
├── api/v1/                   # books, runs, profiles, jobs, eval, stand routers
├── use_cases/                # what routes and tools call; no HTTP inside
├── worker.py                 # lanes gpu and cpu, code hash stamp
├── job_handlers/             # book.py (intake, metadata, layout, structure chain), run.py, evaluation.py
├── job_queue.py              # claim, retry, defer, notify, wait
├── job_specs.py              # pydantic option specs per job type
├── stages/
│   ├── intake.py             # sha, pages, text layer map, bookmarks, contents probe
│   ├── metadata/             # resolve.py, file_metadata.py, title_pages.py,
│   │                         # model_reader.py, language.py, candidates.py (field list)
│   ├── structure/            # the structure: sources/*.py, pages.py (printed pages to book pages), scan.py, reconcile.py, collect.py
│   ├── layout/               # page.py (body, slots, notes), headings.py (level styles from pins), collect.py
│   ├── profile_search.py     # probes, presets, sampled coordinate search
│   ├── assemble.py           # one piece: engine, adapter, rules, checks
│   ├── run_pieces.py         # the run's pieces cut from the structure at the reading level
│   ├── run_state.py          # piece jobs and statuses of a run
│   └── bundle.py             # whole-book numbers, report, bundle
├── engines/                  # borrowed from rag-lab and adapted: converter client, card handover, adapters, model client
├── document/                 # document model (pydantic blocks)
├── rules/                    # knob option implementations that transform the model
├── probes/                   # knob probes
├── writers/markdown.py
├── quality/                  # piece checks, scan measures, book numbers
├── evaluation/               # sets, gates, comparison
├── artifacts.py              # atomic write, manifest, input hash, resume lookup
├── models_client.py          # OpenAI-compatible model client with cache
├── net.py                    # one wrapper for outside calls: retries, hosts set aside (FR-060)
├── book_knobs.py             # book-level knobs and their defaults (FR-059)
├── pdf.py                    # pypdfium2 helpers: pages, text layer, garbled pages
├── settings.py, code_version.py, logging_setup.py
└── orm/                      # SQLAlchemy tables
config/
├── knobs.yaml
├── assembly.yaml             # the assembler's passes and their defaults
├── presets/*.yaml
├── quality.yaml
├── budgets.yaml              # attempts per stage
├── metadata.yaml             # book knob defaults (title-page window)
├── structure.yaml            # structure sources: contents search, then text_layer and scan_layer rules
├── tesseract_languages.yaml  # book languages to Tesseract data for Docling's OCR
├── engines.yaml              # the fields each engine is called with
├── net.yaml                  # retry pauses, set-aside time
├── models.yaml               # model provider per step
└── isbn_agencies.yaml        # ISBN agency names CLDR does not know, to languages
db/
├── migrations/*.sql          # 20261009000001_init (the first five squashed), then profile_candidates and evaluation
└── schema.sql
eval/gold/metadata.yaml       # owner-checked metadata, the SC-010 reference
scripts/
├── check.sh
├── dump_schema.sh
└── check_links.py
tests/
├── unit/                     # document model, writer, reconcile, report numbers
├── stages/                   # each stage on fixture PDFs
├── doors/                    # REST and MCP parity, contracts
└── stand/                    # kill-and-resume, compose smoke
docker-compose.yml
Dockerfile
pyproject.toml
.env.example
```

**Structure Decision**: single Python service with two processes (api and worker) from one image,
mirroring rag-lab's layout so its patterns carry over; stages are modules called by job handlers,
use cases are shared by REST and MCP. Data lives in `data/` (volume, outside git).

## Delivery order

Follows the spec priorities; each step ends runnable and measured.

1. **P0**: compose, migrations, queue and worker with lanes, artifacts and manifest, intake and
   metadata stages, books doors, `wait_job`, stand door.
2. **P1**: structure stage (bookmarks, printed contents and their recognition on scans, chapter files,
   numbering; typography, catalogue and model later), measured against bookmarks before assembly,
   document model, engine adapters, Markdown writer, then a detection scheme per element (code,
   tables, formulas, running heads, images) measured on rag-lab `converter_gold` before any rule,
   piece assembly with default preset, book metrics, report, bundle.
3. **P2**: resume at stage and piece level and the kill-and-resume test; it comes before profile
   search because search multiplies run time and must be cheap to interrupt.
4. **P3**: knob registry loading, probes, presets, sampled search, candidates, node rerun with
   overrides.
5. **P4**: evaluation sets, gates, comparison, `bookmarks_off` and `as_scan` modes.
6. **P5**: doors needed by an external agent to add a knob (registry listing, evaluation on a
   subset, unexpected-change count); the first knob added this way is the acceptance test.
7. **Structure as a tree and the book's layout** (FR-063, FR-064): the two layouts beside the
   system; then the tree in five steps, each gated on the shelf: parent and depth beside `kind`;
   assembly, run and bundle by the tree, the engines reading in today's units and the tree cut at
   its nodes' heading lines; `kind` and the part and chapter lists gone; the internal names
   (stage, tables, config, knobs, response fields) renamed from toc and chapter to structure and
   node; docs, README, diagrams and contracts.

Git init happens before step 1: `.gitignore` with `creds-shared.db`, `data/`, `.env`.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| Own document model besides Docling's | two engines with different outputs, level source per heading, writers independent of engines (Principle V) | DoclingDocument as the core forces MinerU output and our level sources into Docling's schema |
| Shared defaults without a gate before US4 | the evaluation set and gates arrive in US4; until then defaults are first versions, not changes | building evaluation before any stage exists leaves nothing to evaluate; the first US4 evaluation run is registered as the baseline, and Principle VI applies to every change after it |
| Two queue lanes | GPU is one card; CPU stages of other books should not wait behind it (FR-048) | a single serial lane leaves the CPU idle while the GPU converts |
