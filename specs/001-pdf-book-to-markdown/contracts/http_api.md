# HTTP API contract

Base path `/v1`, JSON in and out, errors as `{"error": {"kind": "...", "message": "..."}}` with kind `refused` (400, fix the input),
`busy` (409, the run is still running: wait for it or cancel it first), `missing` (404, no such object yet),
`retry_later` (503, an outside source is set aside) or `fault` (500).
Every route has an MCP tool over the same use case (see `mcp_tools.md`). Long operations return a
job and are followed with `GET /v1/jobs/{id}/wait`.

## Books

| method | path | does | returns |
|---|---|---|---|
| POST | `/books` | JSON `{"shelf_paths": [...], "file_paths": [...], "knobs": {...}, "then": ["metadata", "structure"], "order": "given"}` (paths on the read-only shelf or under `data/inbox`, in order, or sorted by the numbers in their names with `order: "by_number"`); `then` names the stages chained after intake, `run` among them (with `structure`) starting a run once the structure is collected; every file is checked first: a name not ending in `.pdf`, a file without the `%PDF-` header or one PDFium cannot open (a download not finished) is refused and nothing is stored; one book per submission; identity is the ordered list of file hashes | `201 {book}` new, `200 {book}` known (FR-036, FR-054) |
| POST | `/books/upload` | multipart `files` in order and optional `knobs` and `then` JSON fields, the same submission by upload; REST only, an MCP client submits by path | `201 {book}` new, `200 {book}` known |
| GET | `/books` | list, filters `stage`, `q`, `series` (sorted by volume), `min_depth`; `limit`, `offset` page; `brief` (default true) gives short rows | `[book]` |
| GET | `/books/{id}` | catalogue record with metadata fields, structure sources, stage, runs, result run | `{book}` |
| GET | `/books/{id}/bundle` | bundle of the result run (FR-053) as a tar stream | `application/x-tar` |
| GET | `/books/{id}/metadata` | fields with value, source, confidence, attempts | `[field]` |
| GET | `/metadata/coverage` | per field filled, empty, conflicting, low-confidence counts by class (required, sought, optional); books missing a required field | `{coverage}` |
| PATCH | `/books/{id}/metadata/{name}` | manual value, source becomes `manual` | `{field}` |
| GET | `/books/{id}/structure` | the chosen entries with level, level source, parent, pages and votes; `?source=` (`bookmarks` or `printed_contents`) for that source's raw list as the stage read it, with the placement for printed contents; `?version=` for an older version | `{book_id, version, created_at, chosen, depth, entries}` or `{..., source, placement}` |
| POST | `/structure/preview` | `{"book_ids": [...], "knobs": {}}`: the structure on today's code with the knobs tried, no version written; per book moved or not against the current version, in the job's result | `202 {job_id}` |
| GET | `/books/{id}/layout` | `?kind=page` (body size, running-head and folio slots, notes; before the structure) or `?kind=headings` (each level's size, weight, pins in style and label; after it), `?version=` for an older one; a scan answers `skipped` | `{layout}` |
| PATCH | `/books/{id}/knobs` | `{"set": {...}, "unset": [...]}` book-level knobs (FR-059); effective at the next collection | `{knobs, effective}` |
| POST | `/books/recollect` | `{"ids": [] (all), "run": false, "what": ["metadata"], "dry_run": false}`; every stage asked is collected again even when not stale; all ids and stages checked before any job is queued; `dry_run` answers the plan per book (chain, stale, forced, seconds) and the seconds per lane, and queues nothing; the jobs hang under one `batch_job_id`; one job per book | `202 {jobs, batch_job_id}` |
| POST | `/books/{id}/recollect` | `{"what": [...], "run": false, "dry_run": false}` from `intake`, `metadata`, `structure`, `layout`, default `["metadata"]`; every stage asked is collected again even when not stale; a stage not built yet is refused; `run` starts a run once the structure is collected and needs `structure` in `what` (or `what: ["intake"]` alone, which chains the structure); `dry_run` answers the plan (the chain in order with each type's lane: `metadata` then `metadata_gpu` for a scan, `layout_page`, `structure` then `structure_scan` when the book needs the raster, `layout_headings`; which stages are stale; the seconds) and queues nothing; metadata, structure and layouts get new versions, old ones kept (FR-052); `intake` is not versioned: it re-reads the stored files, rewrites the intake artifacts and chains metadata and the structure as on submission | `202 {job_id}` |
| POST | `/books/{id}/read_range` | `{"engine", "first_page", "last_page", "force_raster_only": false}`; reads the range through one engine and keeps the reading, runs untouched; `force_raster_only` (MinerU only) reads every page as a picture, kept with the structure's raster readings | `202 {job_id}` |
| POST | `/shelf/snapshots` | `{"book_ids": null}`; the structure, metadata and layout (page, headings) versions of every book now, kept to compare a change against | `{snapshot}` |
| GET | `/shelf/snapshots` | the snapshots taken: id, when, books | `[snapshot]` |
| GET | `/shelf/snapshots/{id}` | one snapshot: per book its structure, metadata and layout versions | `{snapshot}` |
| GET | `/shelf/snapshots/{id}/changes` | books whose structure or metadata moved since the snapshot, with their layout versions if they moved; `layouts_moved` for books whose layouts alone moved | `{changes}` |

## Runs

| method | path | does | returns |
|---|---|---|---|
| POST | `/books/{id}/runs` | `{"format": "markdown", "profile_id": null, "search": true}`; null profile means the stand assembles one from the preset the book knob `run.preset` names, else the one the page layout's monospace share chooses; the run pins the current metadata, structure and page layout versions (the page layout collected first when missing or stale); `search` answers that profile search was skipped, since it is not built | `202 {run, job_id, search, eta}` |
| POST | `/runs` | `{"book_ids": [...], "format": "markdown"}`; one run per book, as `/books/{id}/runs`, all checked before any is queued; wait_job on `batch_job_id` waits for every run | `202 {runs: [{run_id, book_id, job_id}], batch_job_id}` |
| GET | `/runs` | list, filters `ids`, `book_id`, `status`, `limit`: brief rows with status, stage, code hash and piece counts by status, and for done runs pages and seconds per page | `[run]` |
| GET | `/runs/wait?ids=...&timeout=600&until=all` | long-poll until all (or any) of the named runs end | `{settled, timeout, runs, stopped_runs}` |
| GET | `/runs/compare?a=...&b=...` | two runs of one book side by side, number by number | `{comparison}` |
| POST | `/runs/compare` | `{"pairs": [[a, b], ...], "lines": 5}`: per pair the numbers moved, pieces moved, bundle lines changed and the first few | `{pairs, with_moves, rows}` |
| POST | `/runs/cancel` | `{"ids": [...], "dry_run": false}`; cancels runs and their jobs; `dry_run` lists what it would cancel | `{dry_run, runs: [{run_id, jobs}], skipped}` |
| GET | `/runs/{id}` | status, stage, nodes summary, bundle dir | `{run}` |
| GET | `/runs/{id}/nodes` | per piece: the nodes it holds, status, engine, checks (numbers), errors; `brief=true` leaves out the passes and made_by | `[piece]` |
| POST | `/runs/{id}/nodes/{ord}/rerun` | `{"overrides": {"knob.path": "option"}}`; reassembles the unit holding the node, recomputes book metrics (FR-044); the answer is the run with the `unit` and the `nodes_rerun` with it | `202 {run fields, unit, nodes_rerun}` |
| POST | `/runs/{id}/resume` | resumes a cancelled or `needs_attention` run in place, refused (`busy`) while it runs: pieces not done rerun, and done ones whose inputs changed (code, profile, engine builds, languages, the page layout version); the rest keep their artifacts (FR-023, FR-056) | `202 {run fields, pieces_restarted}` |
| POST | `/runs/{id}/cancel` | cooperative cancel: cancels the run's live jobs, marks the run cancelled and its unfinished pieces failed | `{run fields, jobs_cancelled}` |
| DELETE | `/runs/{id}` | deletes the run, its artifacts and files, refused (`busy`) while it has live jobs; the book's result moves to the next best run (FR-025) | `{deleted, artifacts, was_result, result_run_id}` |
| GET | `/runs/{id}/report` | quality report (`bundle.md` schema) without its per-piece section unless `pieces=true` | `{report}` |
| GET | `/runs/{id}/pages/{page}` | one book page: the pieces holding it, their boundary records there, its blocks (type, engine, box, level, text head), layer words against written words | `{page}` |
| GET | `/runs/{id}/artifacts` | manifest, filters `stage`, `node`, `name` (a substring); per-pass dumps left out unless `heavy=true`; `used=true` adds the probe, structure, metadata and readings the run was made from | `[artifact]` |
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
| GET | `/jobs` | filters `status`, `type`, `run_id`, `book_id` (one value or a list), `lane`, `parent_id`; `before_id` pages; `brief` leaves out options and result | `[job]` |
| GET | `/jobs/{id}` | job with children summary | `{job}` |
| GET | `/jobs/{id}/wait?timeout=600&tree=false` | long-poll until the job and its children finish, the run needs attention (returns failed nodes with errors), or timeout; answers with counts per type and status and the jobs not done, the whole tree with `tree=true` | `{finished: bool, counts, not_done, not_done_total, stopped_runs}` |
| POST | `/jobs/retry` | `{"ids": [...]}`; an `error` or `cancelled` job gets a fresh attempt budget, its last error kept in `waiting_because` | `{changed: [ids]}` |
| POST | `/jobs/pause`, `/jobs/resume`, `/jobs/cancel` | `{"ids": [...]}`; cancel also takes the live jobs under them | `{changed: [ids]}` |
| GET | `/job_types` | every job type with its lane, attempt budget, options schema, whether the worker has a handler for it, and its cost (count, median, p90 seconds of its latest done jobs); a read that took kept readings is priced apart in `cost_kept`, and a queued read counts at the real price in the queue's `seconds_left` | `[job_type]` |
| GET | `/queue` | counts per lane and status, the work in flight by lane and type (filters `book_ids`, `types`), the running jobs with their seconds, seconds left per lane, GPU holder, oldest waiting, runs needing attention | `{stats}` |

## Evaluation

| method | path | does | returns |
|---|---|---|---|
| POST | `/eval/sets` | (planned, not built) `{"name", "members": [{"book_id", "mode"}]}` | `201 {set}` |
| GET | `/eval/sets/{id}` | (planned, not built) members with best known profiles | `{set}` |
| POST | `/eval/gates` | (planned, not built) `{"set_id", "columns", "tolerance", "untouchable"}`; registered before the run | `201 {gate}` |
| POST | `/eval/runs` | (planned, not built) `{"set_id", "gate_id", "baseline_id"}` | `202 {job}` |
| POST | `/eval/structure` | `{"set": "...", "book_ids": [...]}` with set `bookmarks_off`, `contents_off` or `hips`; intake and structure on each book, scored against the gold, the bookmarks, or the structure the bookmarks or printed contents gave with both switched off, before assembly exists (FR-058) | `202 {job}` |
| POST | `/eval/elements` | `{"engines": ["docling", "mineru", "assembled"], "ids": [...], "knobs": {}}`; each engine over rag-lab's converter_gold sections through the stand's adapters, and `assembled` the stand's own assembly of both made with the run knobs in `knobs`, scored per element (code, table cells, headings, text, running heads) against the gold | `202 {job}` |
| GET | `/eval/structure/compare?job_a=...&job_b=...` | two structure evaluations of one set side by side, totals and the books that moved | `{comparison}` |
| GET | `/eval/runs/{id}` | (planned, not built) rows, worse members with reasons, unexpected changes, gate result (FR-028) | `{evaluation_run}` |

## Stand

| method | path | does | returns |
|---|---|---|---|
| POST | `/cleanup` | `{"dry_run": true}` lists the heavy intermediates of runs that are not their book's result with sizes; `false` removes the files and sets `removed_at`; the engines' book-level readings, reports, profiles, measurements, model calls and bundles stay (FR-025) | `{dry_run, files, bytes, runs}` |
| GET | `/stand` | services health, engine builds, GPU holder, outside hosts set aside (FR-060), every worker (a silent one stays listed until a day passes) with its code, lanes, CPU threads and last beat against the code on disk (`worker_behind_disk` null when no worker is alive), shelf mounts | `{stand}` |
| POST | `/stand/worker/reload` | each live worker on older code takes the code on disk once its jobs in hand end; `worker_code` is the one code they run, `mixed` while some are behind | `{requested, worker_code, on_disk, workers, asked \| because}` |
| GET | `/engines/ocr_languages` | book languages Docling's Tesseract can read, installed and installable (`config/tesseract_languages.yaml`) | `{installed, installable}` |
| POST | `/engines/ocr_languages` | `{"language"}`; fetches that language's Tesseract data into `data/tessdata` | `{language, codes, fetched, installed, installable}` |
