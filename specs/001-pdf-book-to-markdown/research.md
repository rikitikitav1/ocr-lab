# Research: PDF Book to Measured Markdown Bundle

Phase 0 of the plan. Each item: decision, rationale, alternatives. Facts about rag-lab come from a
read-only survey of `../rag-lab` on 2026-10-05; facts about headings and tables of contents come
from `~/working_docs/projects/ocr-lab/notes/rag-lab-intake/`.

## R1. Language, packaging, web and MCP

- **Decision**: Python 3.12, uv with a frozen lock, FastAPI plus uvicorn, fastmcp mounted inside the
  same FastAPI app at `/mcp` (stateless HTTP), every MCP tool a thin wrapper over the same use case
  the REST route calls.
- **Rationale**: the same stack runs in rag-lab and its pain points are known; one process for REST
  and MCP keeps the two doors identical (FR-047).
- **Alternatives**: a separate MCP service (two deploys, drift between doors); Go (constitution
  default is Python, engines and PDF libraries are Python).

## R2. Catalogue and state storage

- **Decision**: PostgreSQL 17 (plain image, no pgvector), SQLAlchemy 2 with psycopg, migrations with
  dbmate as a one-shot compose service, `db/schema.sql` dump kept in the repo.
- **Rationale**: owner's choice; the queue needs `FOR UPDATE SKIP LOCKED` and `LISTEN/NOTIFY`;
  metadata fields, profiles and reports are jsonb-friendly; dbmate works well in rag-lab.
- **Alternatives**: SQLite (no concurrent workers, no notify); sharing rag-lab's database (the
  constitution and FR-034 want a separate catalogue).

## R3. Artifact storage and atomic stages

- **Decision**: artifacts on a mounted volume under `data/`: book-level stages per version
  `data/books/<book_id>/<metadata|structure>/v<N>/...`, run stages per run
  `data/runs/<book_id>/<run_id>/<stage>/[<piece>/]...`. Every file is written to a `.tmp` sibling,
  fsynced and renamed into place; then a row in `artifacts` records path, sha256, stage, piece,
  input hash, profile hash and engine builds. A stage is done when its manifest row exists and the
  file sha matches.
- **Rationale**: FR-020 to FR-025: rename is atomic on one filesystem, so a crash never leaves a
  half-written artifact counted as done; the DB row makes "what is done" a query, not a directory
  walk. S3 is explicitly not now.
- **Alternatives**: artifacts as DB blobs (huge rows, engine JSON is megabytes); filesystem only
  without manifest (resume has to trust directory listings).

## R4. Job queue (from rag-lab, with its known weaknesses fixed)

- **Decision**: one `jobs` table, claim with `SELECT ... FOR UPDATE SKIP LOCKED`, two lanes:
  `gpu` (one worker thread, serial, owns the card) and `cpu` (N threads, default 4). Job types are
  stage-sized: `intake`, `metadata`, `structure`, `assemble_piece`, `book_metrics`, `profile_search`,
  `eval_run`. A book run is a parent job that enqueues its stage jobs; piece assembly fans out one
  job per piece. Retries, `Deferred` and `Final` semantics as in rag-lab, except the attempt budget: 3 to 5 per stage from
  `config/budgets.yaml` (FR-057) instead of one global `MAX_ATTEMPTS=3`; backoff
  `60*attempts` s as in rag-lab.
- **Fixes over rag-lab**, from its friction journal:
  - a worker restart killed the running job and lost it: stage and piece checkpoints (R3) make a
    restart cost at most one piece, and `requeue_stale` picks the job up again;
  - jobs were found by polling: `pg_notify` on every state change, and a `wait_job` door
    (long-poll, REST and MCP) that returns when the job or any child finishes;
  - the worker silently ran old code: the worker runs from a copy of `app/` and `config/` made at
    start (`scripts/worker.sh`), so an edit on disk never reaches a running job and lazily imported
    modules never mix two versions; every job row records the copy's hash, the stand door reports
    `worker_behind_disk`, and the worker restarts itself onto newer code once no job is running and
    none is due, so a run started on one version finishes on it (owner, 2026-10-09: refusing new jobs
    froze the queue on every edit);
  - scripts run by `docker compose exec` were invisible: every operation is a job type behind a
    door, there are no exec-only scripts for normal work.
- **GPU handover**: reuse rag-lab's supervisor pattern unchanged: each converter container runs
  `supervisor.py` with `take` and `let_go`; the `gpu` lane calls `take` before a reading and
  `let_go` when switching engines. Piece jobs are ordered by engine within a book to cut
  handovers.
- **Alternatives**: Celery or RQ (another broker, no transactional enqueue with the catalogue);
  one job per book (a restart redoes the book, no per-piece visibility).

## R5. Reusing what rag-lab downloaded

- **Decision**: in this feature, compose references the existing local images by name
  (`rag-lab-converter-docling`, `rag-lab-converter-mineru`) with `pull_policy: never` (their models
  are baked in, so no Hugging Face cache is mounted), reuses the `rag-lab_ollama_data` volume, and
  mounts `../rag-lab/datasets/inbox/books` and
  `../rag-lab/datasets/converter_gold` read-only as the book shelf. The build stamp each image
  carries (`/opt/converter/build.json`, served by `GET /supervisor`) is recorded per reading.
- **Rationale**: SC-009 (no re-download of 10.6 GB and 28 GB images); the stamp keeps runs
  reproducible (Principle VII) even though the image is built elsewhere.
- **Follow-up**: copy `converters/` (Dockerfiles, supervisor, settings) into ocr-lab once its own
  knobs need image changes; until then the images are read-only dependencies.
- **Constraint**: rag-lab and ocr-lab share one GPU. Only one stand runs its converters at a time;
  the ocr-lab stand door reports the card holder.
- **Alternatives**: building ocr-lab's own images now (duplicates 40 GB, nothing to change yet).

## R6. PDF reading library

- **Decision**: pypdfium2 for text layer, bookmarks, per-character font size, weight and position,
  page rendering for scans and images.
- **Rationale**: Apache/BSD licence; rag-lab already uses it (`route.py`) and the typography
  prototype (`book_levels_proto.py`) works on it; pypdf glued words.
- **Alternatives**: PyMuPDF (AGPL; `pymupdf4llm.IdentifyHeaders` is a good model but reimplementable
  in a few dozen lines on pypdfium2 spans).

## R7. Conversion engines and the internal document model

- **Decision**: Docling (docling-serve 1.35.0 in the reused image) for text-layer pages, MinerU
  4.0.7 for pages without a text layer; engine per piece or page range is a knob. Engines are
  called per piece page range (long pieces split at a knob-set page count, with continuation
  marked), never per fixed 50 or 100 page piece. Engine output is translated by an adapter into
  ocr-lab's own document model: a pydantic tree of blocks (heading with level and level source,
  paragraph, code, table, list, figure with image ref, caption, note, page marker). Writers read
  only this model.
- **Rationale**: Principle V (engine quirks stop at the adapter); FR-042 and FR-043 (pieces are
  the unit, levels come from the structure); the `#######` and per-piece style ranking
  defects in rag-lab came from trusting engine levels inside fixed pieces.
- **Alternatives**: DoclingDocument as the internal model (convenient, but MinerU output and our
  level sources would have to be forced into Docling's schema; DoclingDocument becomes an output
  writer in a later feature instead); Marker (GPL code, weights licence with revenue cap).

## R7a. Engines module borrowed from rag-lab

- **Decision**: start `app/engines/` as a copy of rag-lab's engines module (converter client with
  `take_once`, `let_go`, `reading`; `converter_tools` for the docling-serve and MinerU HTTP
  APIs; card handover `hand_to`; the OpenAI-compatible model client) and `converters/supervisor.py`,
  then change it where ocr-lab differs: page ranges per node instead of fixed pieces, build
  stamp and timings recorded per reading into the artifact manifest, adapters into the own
  document model.
- **Rationale**: owner's choice; the module already handles card handover, hung tools, upload
  caching and both engine APIs, which took rag-lab many iterations.
- **Alternatives**: writing engine clients from scratch (repeats solved problems); importing
  rag-lab as a package (couples the two repos' release cycles).

## R8. Metadata sources

- **Decision**: per field, try in order and record every attempt:
  1. PDF info dictionary and XMP (pypdfium2), lowest priority: a scout found it often junk
     (`single.dvi`, `Microsoft Word - ...`, the file name);
  2. title and copyright pages (first and last 20 pages by default, a book knob, or recognised text for scans):
     ISBN by regex with checksum, a 10-digit one only next to an `ISBN` label (random digit runs
     passed the checksum on GoalKicker books); year, publisher, edition, series by patterns;
     a translation carries the original's ISBN too, kept as `original_isbn`;
  3. external catalogues by ISBN, then by title and author: Open Library (English editions; no
     Russian hits in the scout), Labirint book pages (Russian editions: author, translator,
     publisher, year, series, language, pages), Google Books with an API key (the anonymous
     quota was spent); the Russian State Library is left out until its search is worked out;
  4. the stand's model (R12) reading the title and copyright pages for fields still missing or in conflict;
  5. language by `lingua-language-detector` on body text (per-language share for mixed books);
     subject by the stand's model from title, table of contents and blurb.
  Conflicts between sources are resolved by a fixed source priority per field, and a conflict is
  recorded in the field's evidence.
- **Rationale**: SC-010 demands complete metadata wherever any source has it; recording every
  attempt makes "unknown" checkable (FR-038). Scripts do the finding; the model only reads pages
  for what scripts missed and picks among conflicting candidates, so a weak local model is enough.
  Scout: `~/working_docs/projects/ocr-lab/notes/metadata_sources_scout.md`.
- **Alternatives**: model only (expensive, unverifiable); catalogue only (no ISBN in many PDFs).
- **Revised 2026-10-09 (owner's decision)**: step 3 is removed, with the web book cards and SearXNG:
  over the first 15 books the outside sources filled 7 of 140 values, all optional (translators, a
  series, links to other editions), while each site added parsing, rate limits and bans. Every value
  now comes from the book itself; the code stays in git history.

## R9. Structure sources and reconciliation

- **Decision**: sources, each a knob with its own extractor and score:
  bookmarks (pypdfium2 outline), printed contents (rag-lab's dot-leader parser plus a model reading
  contents pages for layouts without dot leaders), numbering grammar in the text, typography
  profile over the whole book (style clustering as in `book_levels_proto.py`: body size is the
  mode, rare styles merge into the nearest common one, running heads are text on many pages),
  external catalogues (Open Library `table_of_contents`, publisher pages), and a model over the
  list of heading candidates as the last source.
  Reconciliation matches entries across sources by normalised title (rapidfuzz) and page,
  resolves printed page numbers to file pages by the offset that maximises matches, keeps per
  entry the level of the highest-ranked source that has it, and stamps that source (FR-009).
  Filtering removes front and back matter that is not body text (contents pages, index, ads for
  other books, blank pages) by a classifier knob.
- **Rationale**: in the rung study, bookmarks exist in all 22 bookmark books, printed contents with
  dot leaders in only 5 of 22, numbering covers a median 6% but agrees 100% where it fires; the
  typography prototype took `#######` from 277 to 0 and sections from 237 to 507.
- **Alternatives**: Docling's built-in heading hierarchy alone (ranks style per chunk; dannyh in one
  piece still put all 16 chapters at levels 6 to 7).
- **Revised 2026-10-09 (owner's decisions, measured on 59 shelf books)**: the toc exists for chapter
  page ranges. Sources read in this feature: bookmarks, printed contents (text layer; on a scan the
  contents window is recognised by MinerU, its index blocks are the entries and its page-number blocks
  give the offset), chapter files, numbering (votes only). Base: the printed contents when the text
  confirms over half of their pages, else bookmarks, else chapter files; titles and pages from the base,
  levels from the bookmarks where an entry has one, the rest moved onto the bookmarks' scale. Printed
  pages are placed by the offset most titles vote for (each title votes for the first page it is on,
  running heads are left out of the text), and a title not found follows the offset of the last one
  found, which carries placement over inserted plates. No contents: at most 100 pages is one chapter,
  longer waits. Typography, the model over heading candidates and catalogues are later sources.
  Measured against bookmarks on 41 books: 1677 of 1681 bookmark chapters start on the same page (±1);
  with printed levels instead of bookmark levels the top level collapsed on 20 books.

## R10. Profile search inside the stand

- **Decision**: the knob registry is `config/knobs.yaml` (groups, knobs, options, one-line help,
  probe name, cost class) with each option bound to a registered Python function. Presets are
  `config/presets/*.yaml`. Search is mechanical: probes run first (cheap, CPU) and pick the preset
  and the knobs worth trying; then coordinate search over those knobs on a sample of pieces
  (first, longest, one with code, one with figures), each candidate scored by the same piece
  checks the report uses; best values are frozen and the full book runs. A model is called only
  by probes that need it (contents pages without dot leaders, subject). Budget per book (number of
  candidates, GPU minutes) is a knob.
- **Rationale**: clarification 1 (as mechanical as possible inside the stand); sampling keeps GPU
  time near one extra pass of the book.
- **Alternatives**: full-book run per candidate (GPU hours per book); model-driven search (not
  mechanical, not reproducible).

## R11. Quality measures

- **Decision**:
  - structure: nodes found against the reconciled structure (recall and level
    agreement), levels within 1..6, no piece below its own sub-nodes, sub-nodes found out of
    those listed (no page threshold for a flat piece);
  - text fidelity on text pages: the share of layer words lost and the share of words not in the
    layer, kept apart rather than folded into one F1, with running heads the engines set aside left
    out;
  - scans: agreement of two engines on the same pages (character-level similarity) and share of
    dictionary words by `wordfreq` for the book's language, plus engine confidence where given;
    calibrated on text books run as scans (FR-049);
  - images and links: every link resolves, every file referenced, decorative images (same image
    hash on many pages) excluded;
  - pieces and the book are reported in numbers with the worst pieces named, no verdict label
    (owner's decision, 2026-10-10).
- **Alternatives**: word similarity only (stays ~98% while structure is wrong).

## R12. Model calls inside the stand

- **Decision**: one OpenAI-compatible chat client, as in rag-lab, pointed at a provider per step by
  a knob: local ollama (the `rag-lab_ollama_data` volume is reused, no model re-pull) or a cheap
  OpenAI-compatible cloud model (DeepSeek and similar), key in `.env`. Steps that call a model:
  metadata from title and copyright pages, subject label, reading contents pages without dot
  leaders, the last-resort level source. Each call records provider, model id and parameters;
  responses are cached by request hash in `model_calls` plus an artifact, so reruns are
  reproducible (FR-026). Unavailable or rate-limited provider: the job is `Deferred` (no attempt
  counted) up to one hour, then the step is marked as tried and failed, never guessed.
- **Not this**: the external agent that designs knobs (Claude Code or similar) is outside the stand
  and talks to it only through MCP tools; the stand never calls it.
- **Rationale**: these steps are narrow (read a page, return fields as JSON), so a smaller model is
  enough and cheaper; the evaluation set shows per step whether it is.
- **Alternatives**: Anthropic API inside the stand (stronger, more expensive, not needed for narrow
  steps; stays possible as a provider option).

## R13. Testing

- **Decision**: pytest with xdist; a scratch database per test module created from
  `db/schema.sql` (rag-lab `real_db.py` pattern); door tests through FastAPI `TestClient` and the
  MCP client; stage tests on small fixture PDFs generated in tests (pypdfium2 cannot write, so
  fixtures are built with reportlab) plus a handful of real pages; a kill-and-resume test that
  stops a worker mid-piece and compares bundles (SC-005); ruff with rag-lab's rule set;
  `scripts/check.sh` runs ruff, then pytest.
- **Alternatives**: testcontainers (slower, rag-lab does fine without).

## R14. Performance and scale

- **Decision**: no time target in this feature (spec: run time not bounded, runs resume). Every
  stage and piece records seconds and GPU seconds so targets can be set after the first
  evaluation run. Scale: one owner; shelf of 135 PDFs in 34 folders, 2074 gold PDFs; evaluation
  set starts at about 25 books.

## R15. First evaluation set

- **Decision**: the 22 bookmark books scored in `rung_scores.md`; the three scans in the rag-lab
  inbox (`unix-4-3bsd-reference`, `analiz-dannyh-genai-python-scan`,
  `cloud-native-docker-k8s-scan`); dannyh (`control-arhitektury-dannyh`, Russian, typography
  prototype); two of the text books also run as scans for FR-049. The best known profile per book
  starts empty and is filled by the first evaluation run.
- **Non-technical books**: the rag-lab shelf is all technical, which the owner considers the
  hardest format (code, tables, sidebars, deep nesting), so it is the right start. A novel, a
  children's book, a school textbook and a poetry collection are easy to find and join the set
  before the first evaluation run, to check that shared behaviour assumes no genre (FR-050).

## R16. External gold sets for the structure stage

- **Decision**: measure the structure stage on its own, before piece assembly exists, on two external
  sets next to our bookmark books:
  - HiPS (github.com/anybass/HiPS): PDFs of doctrinal legal textbooks with ground-truth TOCs as
    `Level, Heading, Page`, levels up to 7; code MIT, data CC BY-NC 4.0, so it is fetched into
    `data/gold/hips/` at a pinned commit and never committed or redistributed. German legal books,
    deep nesting: a genre and a language our shelf does not have.
  - LongDocBench (arXiv 2608.15064, CC BY 4.0): 85 documents (18 textbooks, finance reports,
    papers) up to 105 pages, human-verified TOC trees, scored by tree edit distance (TEDS). The paper
    says it is released, but no data link was found on 2026-10-05; the fetch script records its
    absence until a link appears.
- **Scores**: chapters starting on the right page first (the toc exists for chapter ranges); then
  entry recall and precision (fuzzy title plus page) and level agreement on matched entries. TEDS
  over the TOC tree is dropped (owner, 2026-10-09): it would only put our numbers on LongDocBench's
  scale (best parser 0.55 Macro TEDS), and chapter boundaries are what the stand needs.
- **Metadata window**: the first 20 and the last 20 pages by default (owner's choice), a book knob
  in `config/metadata.yaml`. Measured on the shelf: every book's own ISBN sat on pages 1-6, and pages
  12-18 carried other books' ISBNs; so only the first ISBN is the book's own, a later one becomes the
  original's only next to an original-edition note or, in a Russian book, as the foreign one beside a
  Russian-group ISBN.

