# HTTP API contract

Base path `/v1`, JSON in and out, errors as `{"error": {"kind": "...", "message": "..."}}`.
Every route has an MCP tool over the same use case (see `mcp_tools.md`). Long operations return a
job and are followed with `GET /v1/jobs/{id}/wait`.

## Books

| method | path | does | returns |
|---|---|---|---|
| POST | `/books` | JSON `{"shelf_paths": [...], "file_paths": [...], "knobs": {...}}` (paths on the read-only shelf or under `data/inbox`, in order); one book per submission; identity is the ordered list of file hashes | `201 {book}` new, `200 {book}` known (FR-036, FR-054) |
| POST | `/books/upload` | multipart `files` in order and an optional `knobs` JSON field, the same submission by upload; REST only, an MCP client submits by path | `201 {book}` |
| GET | `/books` | list, filters `stage`, `verdict`, `q`, `series` (sorted by volume) | `[book]` |
| GET | `/books/{id}` | catalogue record with metadata fields, toc sources, stage, runs, result run | `{book}` |
| GET | `/books/{id}/bundle` | bundle of the result run (FR-053) as a tar stream | `application/x-tar` |
| GET | `/books/{id}/metadata` | fields with value, source, confidence, attempts | `[field]` |
| GET | `/metadata/coverage` | per field filled, empty, conflicting, low-confidence counts by class (required, sought, optional); books missing a required field | `{coverage}` |
| PATCH | `/books/{id}/metadata/{name}` | manual value, source becomes `manual` | `{field}` |
| GET | `/books/{id}/toc` | reconciled entries with level source and votes; `?source=` for one source's raw list, `?version=` for an older version | `[entry]` |
| PATCH | `/books/{id}/knobs` | `{"set": {...}, "unset": [...]}` book-level knobs (FR-059); effective at the next collection | `{knobs, effective}` |
| POST | `/books/recollect` | `{"ids": [] (all), "what": ["metadata"]}`; all ids and stages checked before any job is queued; one job per book | `{jobs}` |
| POST | `/books/{id}/recollect` | `{"what": [...]}` from `intake`, `metadata`, `toc`, default `["metadata"]`; a stage not built yet is refused; new versions, old ones kept (FR-052) | `202 {job}` |

## Runs

| method | path | does | returns |
|---|---|---|---|
| POST | `/books/{id}/runs` | `{"format": "markdown", "profile_id": null, "search": true}`; null profile means the stand assembles one | `202 {run, job}` |
| GET | `/runs/{id}` | status, stage, chapters summary, verdict, bundle dir | `{run}` |
| GET | `/runs/{id}/chapters` | per chapter: status, engine, checks, verdict, reasons | `[chapter]` |
| POST | `/runs/{id}/chapters/{ord}/rerun` | `{"overrides": {"knob.path": "option"}}`; reassembles one chapter, recomputes book metrics (FR-044) | `202 {job}` |
| POST | `/runs/{id}/resume` | resumes a failed, cancelled or `needs_attention` run in place; for `needs_attention` only failed chapters rerun (FR-023, FR-056) | `202 {job}` |
| POST | `/runs/{id}/cancel` | cooperative cancel | `{run}` |
| DELETE | `/runs/{id}` | deletes the run and its artifacts; the book's result moves to the next best run (FR-025) | `{deleted, result_run_id}` |
| GET | `/runs/{id}/report` | quality report (`bundle.md` schema) | `{report}` |
| GET | `/runs/{id}/artifacts` | manifest, filters `stage`, `chapter` | `[artifact]` |
| GET | `/runs/{id}/artifacts/{artifact_id}` | file content | raw |
| GET | `/runs/{id}/bundle` | bundle as a tar stream | `application/x-tar` |

## Profiles, knobs, presets

| method | path | does | returns |
|---|---|---|---|
| GET | `/knobs` | registry: groups, knobs, options, help, probe, cost, scope | `{registry}` |
| GET | `/presets` | presets with help | `[preset]` |
| GET | `/profiles/{id}` | values with source and evidence, chapter overrides | `{profile}` |
| POST | `/profiles/{id}/derive` | `{"set": {"knob.path": "option"}}`; new immutable profile, source `manual` (FR-015) | `201 {profile}` |
| GET | `/runs/{id}/candidates` | profile search candidates with scores and decisions (FR-021) | `[candidate]` |

## Jobs

| method | path | does | returns |
|---|---|---|---|
| GET | `/jobs` | filters `status`, `type`, `run_id`, `lane` | `[job]` |
| GET | `/jobs/{id}` | job with children summary | `{job}` |
| GET | `/jobs/{id}/wait?timeout=600` | long-poll until the job and its children finish, the run needs attention (returns failed chapters with errors), or timeout | `{job, finished: bool}` |
| POST | `/jobs/retry` | `{"ids": [...]}`; a failed or cancelled job gets a fresh attempt budget, its last error kept in `waiting_because` | `{changed: [ids]}` |
| POST | `/jobs/pause`, `/jobs/resume`, `/jobs/cancel` | `{"ids": [...]}` or filters | `{changed: n}` |
| GET | `/queue` | counts per lane and status, GPU holder, oldest waiting, runs needing attention | `{stats}` |

## Evaluation

| method | path | does | returns |
|---|---|---|---|
| POST | `/eval/sets` | `{"name", "members": [{"book_id", "mode"}]}` | `201 {set}` |
| GET | `/eval/sets/{id}` | members with best known profiles | `{set}` |
| POST | `/eval/gates` | `{"set_id", "columns", "tolerance", "untouchable"}`; registered before the run | `201 {gate}` |
| POST | `/eval/runs` | `{"set_id", "gate_id", "baseline_id"}` | `202 {job}` |
| GET | `/eval/runs/{id}` | rows, worse members with reasons, unexpected changes, gate result (FR-028) | `{evaluation_run}` |

## Stand

| method | path | does | returns |
|---|---|---|---|
| POST | `/cleanup` | `{"dry_run": true}` lists heavy intermediates of non-result runs and dropped candidates with sizes; `false` removes them (FR-025) | `{files, bytes}` |
| GET | `/stand` | services health, engine builds, GPU holder, outside hosts set aside (FR-060), worker code hash vs disk, shelf mounts | `{stand}` |
