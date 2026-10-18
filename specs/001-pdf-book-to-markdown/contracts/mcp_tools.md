# MCP tools contract

One FastMCP server `ocr-lab` mounted at `/mcp` in the API process. Each tool calls the same use
case as the REST route named next to it, with the same arguments and result shape. A failed tool's
error text starts with the same kind the route returns: `refused:`, `busy:`, `missing:`, `retry_later:` or `fault:`.

| tool | route | notes |
|---|---|---|
| `add_book(file_paths?, shelf_paths?, knobs?, then?, order="given")` | POST `/books` | ordered lists; paths the API container can read; `run` in `then` needs `structure`; returns the book with `created` and the intake `job_id` (wait_job on it waits for the whole chain; null when the book was known) |
| `books(stage?, q?, series?, limit=100, offset=0, brief=true, min_depth?)` | GET `/books` | |
| `book(id)` | GET `/books/{id}` | includes metadata, structure sources, the result run, whether metadata, structure and the two layouts are stale, and the eta of work queued for it |
| `book_bundle(id)` | GET `/books/{id}/bundle` | returns the bundle path; the tar stream stays REST-only |
| `metadata(id)` | GET `/books/{id}/metadata` | |
| `metadata_coverage()` | GET `/metadata/coverage` | |
| `set_metadata(id, name, value)` | PATCH `/books/{id}/metadata/{name}` | |
| `structure(id, source?, version?)` | GET `/books/{id}/structure` | |
| `layout(id, kind="page", version?)` | GET `/books/{id}/layout` | |
| `set_book_knobs(id, set?, unset?)` | PATCH `/books/{id}/knobs` | |
| `recollect_books(ids?, what?, run?, dry_run?)` | POST `/books/recollect` | empty ids are the whole shelf; answers batch_job_id |
| `recollect(id, what?, run?, dry_run?)` | POST `/books/{id}/recollect` | |
| `read_range(id, engine, first_page, last_page, force_raster_only?)` | POST `/books/{id}/read_range` | |
| `shelf_snapshot(book_ids?)`, `shelf_changes(id, book_ids?)`, `shelf_snapshots()`, `shelf_snapshot_read(id)` | POST `/shelf/snapshots`, GET `/shelf/snapshots/{id}/changes`, GET `/shelf/snapshots`, GET `/shelf/snapshots/{id}` | |
| `start_run(id, format="markdown", profile_id?, search=true)` | POST `/books/{id}/runs` | returns the run, job_id, an eta, and `search` saying profile search was skipped (not built) |
| `start_runs(book_ids, format?)`, `runs(ids?, book_id?, status?, limit?)`, `wait_runs(ids, timeout?, until?)`, `cancel_runs(ids, dry_run?)` | POST `/runs`, GET `/runs`, GET `/runs/wait`, POST `/runs/cancel` | bulk |
| `compare_runs(a, b, keys?)`, `compare_run_pairs(pairs, lines?)` | GET `/runs/compare`, POST `/runs/compare` | |
| `page(id, page)` | GET `/runs/{id}/pages/{page}` | |
| `structure_preview(book_ids, knobs?)` | POST `/structure/preview` | a job; its result holds the diff |
| `run(id)` | GET `/runs/{id}` | |
| `nodes(id, brief=false)` | GET `/runs/{id}/nodes` | |
| `rerun_node(id, ord, overrides?)` | POST `/runs/{id}/nodes/{ord}/rerun` | |
| `resume_run(id)`, `cancel_run(id)` | POST resume, cancel | |
| `delete_run(id)` | DELETE `/runs/{id}` | refused while the run has live jobs |
| `cleanup(dry_run=true)` | POST `/cleanup` | book-level engine readings are never removed |
| `report(id, pieces=false)` | GET `/runs/{id}/report` | |
| `bundle(id)` | GET `/runs/{id}/bundle` | returns the bundle path |
| `reassemble(id, knobs, ords?, reading_level?, reread=true)` | POST `/runs/{id}/reassemble` | |
| `run_artifacts(id, stage?, node?, used=false, heavy=false, name?)` | GET `/runs/{id}/artifacts` | `used` adds the book's artifacts the run was made from, marked used; per-pass dumps only with `heavy`; `name` keeps the names holding it |
| `run_artifact(id, artifact_id)` | GET `/runs/{id}/artifacts/{aid}` | the whole file as text; the route sends it raw |
| `artifact(id)` | GET `/artifacts/{id}` | any kept artifact, a book's too, with its file content as text |
| `knobs()`, `presets()` | GET `/knobs`, `/presets` | |
| `profile(id)`, `derive_profile(id, set, pieces)` | GET, POST derive | |
| `candidates(id)` | GET `/runs/{id}/candidates` | planned, not built |
| `jobs(status?, type?, run_id?, book_id?, lane?, limit=100, parent_id?, before_id?, brief=false)`, `job(id)` | GET `/jobs`, `/jobs/{id}` | |
| `wait_job(id, timeout=600, tree=false)` | GET `/jobs/{id}/wait` | replaces polling loops; counts and jobs not done, the whole tree on request |
| `retry_jobs`, `pause_jobs`, `resume_jobs`, `cancel_jobs` | POST `/jobs/*` | bulk |
| `queue(book_ids?, types?)` | GET `/queue` | wait tools over MCP answer within 240 s |
| `job_types()` | GET `/job_types` | lane, attempts, options schema, built, cost, cost_kept |
| `create_eval_set`, `eval_set`, `register_gate`, `start_eval_run`, `eval_run` | `/eval/*` | planned, not built |
| `structure_eval(set, book_ids?)` | POST `/eval/structure` | |
| `structure_eval_compare(job_a, job_b)` | GET `/eval/structure/compare` | |
| `element_eval(engines?, ids?, knobs?)` | POST `/eval/elements` | |
| `stand()` | GET `/stand` | |
| `reload_worker()` | POST `/stand/worker/reload` | |
| `ocr_languages()`, `install_ocr_language(language)` | GET, POST `/engines/ocr_languages` | Docling's Tesseract data |

A door test asserts that every route has a tool and every tool a route.
