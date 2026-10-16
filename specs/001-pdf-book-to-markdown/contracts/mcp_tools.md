# MCP tools contract

One FastMCP server `ocr-lab` mounted at `/mcp` in the API process. Each tool calls the same use
case as the REST route named next to it, with the same arguments and result shape. A failed tool's
error text starts with the same kind the route returns: `refused:`, `missing:`, `retry_later:` or `fault:`.

| tool | route | notes |
|---|---|---|
| `add_book(file_paths?, shelf_paths?, knobs?, then?)` | POST `/books` | ordered lists; paths the API container can read; `run` in `then` needs `structure` |
| `books(stage?, q?, series?)` | GET `/books` | |
| `book(id)` | GET `/books/{id}` | includes metadata, structure sources and the result run |
| `book_bundle(id)` | GET `/books/{id}/bundle` | returns the bundle path; the tar stream stays REST-only |
| `metadata(book_id)` | GET `/books/{id}/metadata` | |
| `metadata_coverage()` | GET `/metadata/coverage` | |
| `set_metadata(book_id, name, value)` | PATCH `/books/{id}/metadata/{name}` | |
| `structure(book_id, source?, version?)` | GET `/books/{id}/structure` | |
| `layout(book_id, kind?, version?)` | GET `/books/{id}/layout` | |
| `set_book_knobs(book_id, set?, unset?)` | PATCH `/books/{id}/knobs` | |
| `recollect_books(ids?, what?, force?, run?)` | POST `/books/recollect` | empty ids are the whole shelf |
| `recollect(book_id, what, force?, run?)` | POST `/books/{id}/recollect` | |
| `read_range(id, engine, first_page, last_page, force_raster_only?)` | POST `/books/{id}/read_range` | |
| `shelf_snapshot(book_ids?)`, `shelf_changes(id, book_ids?)` | POST `/shelf/snapshots`, GET `/shelf/snapshots/{id}/changes` | |
| `start_run(book_id, format="markdown", profile_id?, search=true)` | POST `/books/{id}/runs` | |
| `start_runs(book_ids, format?)`, `runs(ids?, book_id?, status?, limit?)`, `wait_runs(ids, timeout?, until?)`, `cancel_runs(ids, dry_run?)` | POST `/runs`, GET `/runs`, GET `/runs/wait`, POST `/runs/cancel` | bulk |
| `compare_runs(a, b, keys?)` | GET `/runs/compare` | |
| `run(id)` | GET `/runs/{id}` | |
| `nodes(run_id)` | GET `/runs/{id}/nodes` | |
| `rerun_node(run_id, ord, overrides)` | POST `/runs/{id}/nodes/{ord}/rerun` | |
| `resume_run(run_id)`, `cancel_run(run_id)` | POST resume, cancel | |
| `delete_run(run_id)` | DELETE `/runs/{id}` | planned, not built |
| `cleanup(dry_run=true)` | POST `/cleanup` | planned, not built |
| `report(run_id)` | GET `/runs/{id}/report` | |
| `bundle(run_id)` | GET `/runs/{id}/bundle` | returns the bundle path |
| `reassemble(run_id, knobs, ords?, reading_level?, reread?)` | POST `/runs/{id}/reassemble` | |
| `run_artifacts(run_id, stage?, node?)` | GET `/runs/{id}/artifacts` | |
| `run_artifact(run_id, artifact_id, max_bytes=200000)` | GET `/runs/{id}/artifacts/{aid}` | text truncated with a marker |
| `artifact(id)` | GET `/artifacts/{id}` | any kept artifact, a book's too |
| `knobs()`, `presets()` | GET `/knobs`, `/presets` | |
| `profile(id)`, `derive_profile(id, set, pieces)` | GET, POST derive | |
| `candidates(run_id)` | GET `/runs/{id}/candidates` | planned, not built |
| `jobs(status?, type?, run_id?, book_id?, lane?)`, `job(id)` | GET `/jobs`, `/jobs/{id}` | |
| `wait_job(id, timeout=600, tree=false)` | GET `/jobs/{id}/wait` | replaces polling loops; counts and jobs not done, the whole tree on request |
| `retry_jobs`, `pause_jobs`, `resume_jobs`, `cancel_jobs` | POST `/jobs/*` | bulk |
| `queue()` | GET `/queue` | |
| `job_types()` | GET `/job_types` | lane, attempts, options schema, built |
| `create_eval_set`, `eval_set`, `register_gate`, `start_eval_run`, `eval_run` | `/eval/*` | planned, not built |
| `structure_eval(set, book_ids?)` | POST `/eval/structure` | |
| `structure_eval_compare(job_a, job_b)` | GET `/eval/structure/compare` | |
| `element_eval(engines?, ids?)` | POST `/eval/elements` | |
| `stand()` | GET `/stand` | |
| `reload_worker()` | POST `/stand/worker/reload` | |
| `ocr_languages()`, `install_ocr_language(language)` | GET, POST `/engines/ocr_languages` | Docling's Tesseract data |

A door test asserts that every route has a tool and every tool a route.
