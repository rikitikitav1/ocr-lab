# HTTP API contract

Base path `/v1`, JSON in and out, errors as `{"error": {"kind": "...", "message": "..."}}` with kind `refused` (400, fix the input),
`missing` (404, no such object yet), `retry_later` (503, an outside source is set aside) or `fault` (500).
Every route has an MCP tool over the same use case (see `mcp_tools.md`). Long operations return a
job and are followed with `GET /v1/jobs/{id}/wait`.

## Books

| method | path | does | returns |
|---|---|---|---|
| POST | `/books` | JSON `{"shelf_paths": [...], "file_paths": [...], "knobs": {...}, "then": ["metadata", "structure"]}` (paths on the read-only shelf or under `data/inbox`, in order); `then` names the stages chained after intake, `run` among them (with `structure`) starting a run once the structure is collected; every file is checked first: a name not ending in `.pdf`, a file without the `%PDF-` header or one PDFium cannot open (a download not finished) is refused and nothing is stored; one book per submission; identity is the ordered list of file hashes | `201 {book}` new, `200 {book}` known (FR-036, FR-054) |
| POST | `/books/upload` | multipart `files` in order and an optional `knobs` JSON field, the same submission by upload; REST only, an MCP client submits by path | `201 {book}` |
| GET | `/books` | list, filters `stage`, `q`, `series` (sorted by volume) | `[book]` |
| GET | `/books/{id}` | catalogue record with metadata fields, structure sources, stage, runs, result run | `{book}` |
| GET | `/books/{id}/bundle` | bundle of the result run (FR-053) as a tar stream | `application/x-tar` |
| GET | `/books/{id}/metadata` | fields with value, source, confidence, attempts | `[field]` |
| GET | `/metadata/coverage` | per field filled, empty, conflicting, low-confidence counts by class (required, sought, optional); books missing a required field | `{coverage}` |
| PATCH | `/books/{id}/metadata/{name}` | manual value, source becomes `manual` | `{field}` |
| GET | `/books/{id}/structure` | reconciled nodes with level, level source and votes; `?source=` for one source's raw list, `?version=` for an older version | `[node]` |
| GET | `/books/{id}/layout` | `?kind=page` (body size, running-head and folio slots, notes; before the structure) or `?kind=headings` (each level's size, weight, pins in style and label; after it), `?version=` for an older one; a scan answers `skipped` | `{layout}` |
| PATCH | `/books/{id}/knobs` | `{"set": {...}, "unset": [...]}` book-level knobs (FR-059); effective at the next collection | `{knobs, effective}` |
| POST | `/books/recollect` | `{"ids": [] (all), "run": false, "force": false, "what": ["metadata"]}`; all ids and stages checked before any job is queued; one job per book | `202 {jobs}` |
| POST | `/books/{id}/recollect` | `{"run": false, "force": false, "what": [...]}` from `intake`, `metadata`, `structure`, `layout`, default `["metadata"]`; a stage not built yet is refused; `run` starts a run once the structure is collected and needs `structure` in `what`; metadata, structure and layouts get new versions, old ones kept (FR-052); `intake` is not versioned: it re-reads the stored files, rewrites the intake artifacts and chains metadata as on submission | `202 {job_id}` |
| POST | `/books/{id}/read_range` | `{"engine", "first_page", "last_page", "force_raster_only": false}`; reads the range through one engine and keeps the reading, runs untouched; `force_raster_only` (MinerU only) reads every page as a picture, kept with the structure's raster readings | `202 {job_id}` |
| POST | `/shelf/snapshots` | `{"book_ids": null}`; the structure and metadata of every book now, kept to compare a change against | `{snapshot}` |
| GET | `/shelf/snapshots/{id}/changes` | books whose structure or metadata moved since the snapshot | `{changes}` |

## Runs

| method | path | does | returns |
|---|---|---|---|
| POST | `/books/{id}/runs` | `{"format": "markdown", "profile_id": null, "search": true}`; null profile means the stand assembles one | `202 {run, job}` |
| POST | `/runs` | `{"book_ids": [...], "format": "markdown"}`; one run per book, as `/books/{id}/runs`, all checked before any is queued | `202 {runs}` |
| GET | `/runs` | list, filters `ids`, `book_id`, `status`, `limit` | `[run]` |
| GET | `/runs/wait?ids=...&timeout=600&until=all` | long-poll until all (or any) of the named runs end | `{settled, timeout, runs, stopped_runs}` |
| GET | `/runs/compare?a=...&b=...` | two runs of one book side by side, number by number | `{comparison}` |
| POST | `/runs/cancel` | `{"ids": [...], "dry_run": false}`; cancels runs and their jobs | `{runs, skipped}` |
| GET | `/runs/{id}` | status, stage, nodes summary, bundle dir | `{run}` |
| GET | `/runs/{id}/nodes` | per piece: the nodes it holds, status, engine, checks (numbers), errors | `[piece]` |
| POST | `/runs/{id}/nodes/{ord}/rerun` | `{"overrides": {"knob.path": "option"}}`; reassembles the unit holding the node, recomputes book metrics (FR-044); the answer names the `unit` and the `nodes_rerun` with it | `202 {run, unit, nodes_rerun}` |
| POST | `/runs/{id}/resume` | resumes a failed, cancelled or `needs_attention` run in place; for `needs_attention` only failed nodes rerun (FR-023, FR-056) | `202 {job}` |
| POST | `/runs/{id}/cancel` | cooperative cancel | `{run}` |
| DELETE | `/runs/{id}` | (planned, not built) deletes the run and its artifacts; the book's result moves to the next best run (FR-025) | `{deleted, result_run_id}` |
| GET | `/runs/{id}/report` | quality report (`bundle.md` schema) | `{report}` |
| GET | `/runs/{id}/artifacts` | manifest, filters `stage`, `node` | `[artifact]` |
| GET | `/runs/{id}/artifacts/{artifact_id}` | file content | raw |
| GET | `/runs/{id}/bundle` | bundle as a tar stream | `application/x-tar` |
| POST | `/runs/{id}/reassemble` | `{"knobs": {...}, "ords": [...], "reading_level": 0, "reread": true}` (CPU lane; the level cuts the run at that tree level instead of its own, reread false leaves out the next piece's first page, as runs read before the re-read were cut, units_not_pieces names the run's units no piece matches, not_kept the pieces whose pages the run did not read that way); assembles the run's nodes again from their kept readings with run knobs set, each node's numbers before and after, and today's code against what the run kept (numbers and text changed, headings moved, the anchors left out); empty knobs give only the latter; the run untouched | `202 {job_id}` |
| GET | `/artifacts/{id}` | any kept artifact by id: stage, name, book, run, node, meta and its text | `{artifact}` |

## Profiles, knobs, presets

| method | path | does | returns |
|---|---|---|---|
| GET | `/knobs` | registry: groups, knobs, options, help, probe, cost, scope | `{registry}` |
| GET | `/presets` | presets with help | `[preset]` |
| GET | `/profiles/{id}` | values with source and evidence, piece overrides | `{profile}` |
| POST | `/profiles/{id}/derive` | `{"set": {"knob.path": "option"}, "pieces": {"<ord>": {"knob.path": "option"}}}`; new immutable profile, source `manual`; the same values for the same book give the existing profile (FR-015) | `201 {profile}` |
| GET | `/runs/{id}/candidates` | (planned, not built) profile search candidates with scores and decisions (FR-021) | `[candidate]` |

## Jobs

| method | path | does | returns |
|---|---|---|---|
| GET | `/jobs` | filters `status`, `type`, `run_id`, `book_id`, `lane` | `[job]` |
| GET | `/jobs/{id}` | job with children summary | `{job}` |
| GET | `/jobs/{id}/wait?timeout=600&tree=false` | long-poll until the job and its children finish, the run needs attention (returns failed nodes with errors), or timeout; answers with counts per type and status and the jobs not done, the whole tree with `tree=true` | `{finished: bool, counts, not_done, stopped_runs}` |
| POST | `/jobs/retry` | `{"ids": [...]}`; an `error` or `cancelled` job gets a fresh attempt budget, its last error kept in `waiting_because` | `{changed: [ids]}` |
| POST | `/jobs/pause`, `/jobs/resume`, `/jobs/cancel` | `{"ids": [...]}` or filters | `{changed: n}` |
| GET | `/job_types` | every job type with its lane, attempt budget, options schema and whether the worker has a handler for it | `[job_type]` |
| GET | `/queue` | counts per lane and status, GPU holder, oldest waiting, runs needing attention | `{stats}` |

## Evaluation

| method | path | does | returns |
|---|---|---|---|
| POST | `/eval/sets` | (planned, not built) `{"name", "members": [{"book_id", "mode"}]}` | `201 {set}` |
| GET | `/eval/sets/{id}` | (planned, not built) members with best known profiles | `{set}` |
| POST | `/eval/gates` | (planned, not built) `{"set_id", "columns", "tolerance", "untouchable"}`; registered before the run | `201 {gate}` |
| POST | `/eval/runs` | (planned, not built) `{"set_id", "gate_id", "baseline_id"}` | `202 {job}` |
| POST | `/eval/structure` | `{"set": "...", "book_ids": [...]}` with set `hips`, `longdocbench` or `bookmarks_off`; intake and structure on each book, scored against the gold or the bookmarks, before assembly exists (FR-058) | `202 {job}` |
| POST | `/eval/elements` | `{"engines": ["docling", "mineru"], "ids": [...]}`; each engine over rag-lab's converter_gold sections through the stand's adapters, scored per element (code, table cells, headings, text, running heads) against the gold | `202 {job}` |
| GET | `/eval/structure/compare?job_a=...&job_b=...` | two structure evaluations of one set side by side, totals and the books that moved | `{comparison}` |
| GET | `/eval/runs/{id}` | (planned, not built) rows, worse members with reasons, unexpected changes, gate result (FR-028) | `{evaluation_run}` |

## Stand

| method | path | does | returns |
|---|---|---|---|
| POST | `/cleanup` | (planned, not built) `{"dry_run": true}` lists heavy intermediates of non-result runs and dropped candidates with sizes; `false` removes them (FR-025) | `{files, bytes}` |
| GET | `/stand` | services health, engine builds, GPU holder, outside hosts set aside (FR-060), worker code hash vs disk, shelf mounts | `{stand}` |
| POST | `/stand/worker/reload` | the worker takes newer code once its jobs in hand end; asked only when it runs older code | `{requested, because}` |
| GET | `/engines/ocr_languages` | book languages Docling's Tesseract can read, installed and installable (`config/tesseract_languages.yaml`) | `{installed, installable}` |
| POST | `/engines/ocr_languages` | `{"language"}`; fetches that language's Tesseract data into `data/tessdata` | `{language, codes, fetched, installed, installable}` |
