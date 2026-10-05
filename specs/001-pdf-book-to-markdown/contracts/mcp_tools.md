# MCP tools contract

One FastMCP server `ocr-lab` mounted at `/mcp` in the API process. Each tool calls the same use
case as the REST route named next to it, with the same arguments and result shape.

| tool | route | notes |
|---|---|---|
| `add_book(file_paths?, shelf_paths?, knobs?)` | POST `/books` | ordered lists; paths the API container can read |
| `books(stage?, verdict?, q?, series?)` | GET `/books` | |
| `book(id)` | GET `/books/{id}` | includes metadata, toc sources and the result run |
| `book_bundle(id)` | GET `/books/{id}/bundle` | returns the bundle path; the tar stream stays REST-only |
| `metadata_coverage()` | GET `/metadata/coverage` | |
| `set_metadata(book_id, name, value)` | PATCH `/books/{id}/metadata/{name}` | |
| `toc(book_id, source?, version?)` | GET `/books/{id}/toc` | |
| `set_book_knobs(book_id, set?, unset?)` | PATCH `/books/{id}/knobs` | |
| `recollect_books(ids?, what?)` | POST `/books/recollect` | |
| `recollect(book_id, what)` | POST `/books/{id}/recollect` | |
| `start_run(book_id, format="markdown", profile_id?, search=true)` | POST `/books/{id}/runs` | |
| `run(id)` | GET `/runs/{id}` | |
| `chapters(run_id)` | GET `/runs/{id}/chapters` | |
| `rerun_chapter(run_id, ord, overrides)` | POST `/runs/{id}/chapters/{ord}/rerun` | |
| `resume_run(run_id)`, `cancel_run(run_id)` | POST resume, cancel | |
| `delete_run(run_id)` | DELETE `/runs/{id}` | |
| `cleanup(dry_run=true)` | POST `/cleanup` | |
| `report(run_id)` | GET `/runs/{id}/report` | |
| `artifacts(run_id, stage?, chapter?)` | GET `/runs/{id}/artifacts` | |
| `artifact(run_id, artifact_id, max_bytes=200000)` | GET `/runs/{id}/artifacts/{aid}` | text truncated with a marker |
| `knobs()`, `presets()` | GET `/knobs`, `/presets` | |
| `profile(id)`, `derive_profile(id, set)` | GET, POST derive | |
| `candidates(run_id)` | GET `/runs/{id}/candidates` | |
| `jobs(status?, type?, run_id?)`, `job(id)` | GET `/jobs`, `/jobs/{id}` | |
| `wait_job(id, timeout=600)` | GET `/jobs/{id}/wait` | replaces polling loops |
| `retry_jobs`, `pause_jobs`, `resume_jobs`, `cancel_jobs` | POST `/jobs/*` | bulk |
| `queue()` | GET `/queue` | |
| `create_eval_set`, `eval_set`, `register_gate`, `start_eval_run`, `eval_run` | `/eval/*` | |
| `stand()` | GET `/stand` | |

A door test asserts that every route has a tool and every tool a route.
