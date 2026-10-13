# Data Model: PDF Book to Measured Markdown Bundle

Tables live in PostgreSQL; large payloads (engine output, document model, bundle files) live as
artifacts on disk and are referenced by `artifacts` rows (research R3). Ids are `bigint` identity
unless noted. Every table has `created_at`.

## books

The catalogue record (spec: Source book, Catalogue record).

| field | type | notes |
|---|---|---|
| id | bigint | |
| sha256 | text unique | identity: hash of the ordered file sha256 list (FR-036, FR-054) |
| pages | int | total across files |
| text_layer | jsonb | per page: `layer`, `none`; plus counts |
| has_bookmarks | bool | |
| has_printed_contents | bool | null until probed |
| toc_sources | jsonb | sources found at intake, with entry counts |
| stage | text | current stage, see state machine |
| result_run_id | fk runs | best finished run (FR-053), recomputed when a run finishes |
| knobs | jsonb | book-level knob overrides (FR-059): `metadata.title_pages.head`, `metadata.title_pages.tail`, `toc.contents_pages`, `toc.skip_root_bookmark`, `toc.ignore_bookmarks`, `toc.chapter_label`, `toc.from_headings` |
| page_offset | int | book page minus printed page number, measured on the printed contents when the text confirms most entries, whichever toc source won; null otherwise |

## metadata_fields

One row per book and field (FR-037, FR-038).

| field | type | notes |
|---|---|---|
| metadata_version_id | fk metadata_versions | |
| name | text | `title`, `authors`, `edition`, `year`, `languages`, `publisher`, `series`, `volume`, `isbn`, `subject`, `pages`, and the optional `original_title`; `year` is the year of this edition or translation |
| value | jsonb | null when unknown |
| source | text | `file_metadata`, `title_pages`, `imprint`, `model`, `detector`, `intake`, `manual` |
| confidence | real | 0..1 |
| attempts | jsonb | every source tried, with outcome (`found`, `absent`, `conflict`, `failed`) |
| unique | | (metadata_version_id, name) |

Rule: `value is null` requires `attempts` to list every source applicable to the field.

## book_files

Files of a book in order (FR-054); a one-file book has one row.

| field | type | notes |
|---|---|---|
| book_id | fk books | |
| ord | int | position in the book |
| sha256 | text | file content hash |
| file_path | text | stored original under `data/files/<sha[:2]>/<sha>.pdf`, stored once by content and linked from the book's folder as `data/books/<id>/source/<ord>-<file name>` |
| file_name | text | name as submitted |
| pages | int | |
| first_page | int | book page number of the file's first page |
| unique | | (book_id, ord) |

Volumes are not files of one book: each volume is its own book, and volumes are linked by the
`series` and `volume` metadata fields (FR-055).

Book pages are numbered across files; artifacts and reports carry `(file ord, in-file page)` next
to the book page.

## metadata_versions, toc_versions

Book-level results are versioned (FR-052).

| field | type | notes |
|---|---|---|
| id | bigint | |
| book_id | fk books | |
| version | int | 1, 2, ... per book |
| input_hash | text | knobs of the stage plus code hash of its sources; a change triggers recollection |
| job_id | fk jobs | the job that collected it |
| current | bool | one current version per book and kind |

`metadata_fields` and `toc_entries` hang off a version, not off the book or a run. A manual
metadata edit (FR-051) creates a new metadata version that copies the rest.

## toc_entries

Reconciled table of contents (FR-008, FR-009, FR-043).

| field | type | notes |
|---|---|---|
| id | bigint | |
| toc_version_id | fk toc_versions | |
| ord | int | order in the book |
| title | text | |
| level | int | 1..6 |
| level_source | text | `bookmarks`, `printed_contents`, `numbering`, `typography`, `catalogue`, `model` |
| first_page, last_page | int | book pages, numbered across files; the file and in-file page come from `book_files.first_page` |
| kind | text | `chapter`, `part`, `section`, `front_matter`, `back_matter` (filtered entries are kept with their kind) |
| votes | jsonb | which sources had this entry, with their levels |

## knobs (config, not a table)

`config/knobs.yaml`: groups → knobs → options. Each knob: `name`, `help` (one line), `options`,
`probe` (registered probe name or null), `cost` (`cpu`, `gpu`, `model`), `scope` (`book`,
`chapter`). Each option names a registered implementation. Loaded and validated at start; a door
lists it.

## presets (config, not a table)

`config/presets/<name>.yaml`: a partial profile (knob path → option) with a one-line help and the
probe signature that suggests it.

## profiles

Resolved profile of a book (FR-012 to FR-015).

| field | type | notes |
|---|---|---|
| id | bigint | |
| book_id | fk books | |
| preset | text | |
| values | jsonb | knob path → `{option, source, evidence}`; source is `preset`, `probe`, `search`, `manual` |
| chapter_overrides | jsonb | chapter ord → knob path → option (FR-044) |
| sha256 | text | hash of the canonical resolved form, stamped on runs and artifacts |
| parent_id | fk profiles | the profile it was derived from (manual edit or search) |

Profiles are immutable; an edit creates a new row.

## profile_candidates

Every candidate the search tried (FR-021).

| field | type | notes |
|---|---|---|
| search_job_id | fk jobs | |
| profile_values | jsonb | |
| sample_chapters | int[] | |
| scores | jsonb | chapter checks per sampled chapter |
| decision | text | `kept`, `dropped` |
| reason | text | |

## runs

One processing of one book with one profile (spec: Run).

| field | type | notes |
|---|---|---|
| id | bigint | |
| book_id | fk books | |
| profile_id | fk profiles | |
| metadata_version_id | fk metadata_versions | version the run used |
| toc_version_id | fk toc_versions | version the run used |
| format | text | `markdown` in this feature |
| dir | text | `data/runs/<book_id>/<run_id>` |
| status | text | `queued`, `running`, `needs_attention`, `done`, `failed`, `cancelled` |
| stage | text | current stage |
| code_hash | text | hash of `app/` the worker ran |
| engine_builds | jsonb | build stamps of engines used |
| bundle_dir | text | set when done |

## chapters

Chapter of a run (spec: Chapter; FR-042, FR-044, FR-046).

| field | type | notes |
|---|---|---|
| run_id | fk runs | |
| ord | int | matches the toc entry |
| toc_entry_id | fk toc_entries | |
| status | text | `pending`, `running`, `done`, `failed` (error kept in `errors`) |
| engine | text | |
| checks | jsonb | chapter numbers: text lost and not in the layer, sub-entries found, headings, figures, pass counts |
| errors | jsonb | why a failed chapter failed |
| seconds, gpu_seconds | real | |
| unique | | (run_id, ord) |

## artifacts

Manifest of stage artifacts (FR-020, FR-022, FR-023).

| field | type | notes |
|---|---|---|
| id | bigint | |
| run_id | fk runs | null for book-level stages |
| metadata_version_id, toc_version_id | fk | set for versioned book-level stages |
| book_id | fk books | set for intake, which belongs to the book itself; a row has one owner among run and versions, or only the book |
| stage | text | |
| chapter_ord | int | null for book-level stages |
| name | text | e.g. `toc.bookmarks.json`, `engine.docling.p101-140.json`, `model.after.drop_running_heads.json` |
| path | text | relative to `data/` (run artifacts under `runs/<book_id>/<run_id>/`, versioned book-level ones under `books/<book_id>/metadata/v<N>/` and `books/<book_id>/toc/v<N>/`) |
| sha256 | text | |
| input_hash | text | hash of inputs, profile sha and engine builds; reuse on resume only if equal |
| meta | jsonb | engine build, knobs applied, model call ids |
| heavy | bool | raw engine output or per-rule model dump; only these are removed by cleanup |
| removed_at | timestamptz | set by cleanup; the row stays as a record |

## model_calls

Cached model calls (FR-026).

| field | type | notes |
|---|---|---|
| request_hash | text pk | provider, model id, parameters and prompt |
| provider | text | `ollama` or the cloud provider; part of the hash, since one model name may live in both |
| model | text | |
| params | jsonb | |
| response_path | text | artifact path of the response |
| tokens_in, tokens_out | int | |
| created_at | timestamptz | |

## outside_hosts

Hosts that failed recently, so every caller waits out the same pause instead of each finding it again (`app/net.py`).

| field | type | notes |
|---|---|---|
| host | text pk | |
| until | timestamptz | no call to the host before this time |
| reason | text | the last failure |
| updated_at | timestamptz | |

## jobs

Queue (research R4).

| field | type | notes |
|---|---|---|
| id | bigint | |
| type | text | `book_run`, `intake`, `metadata`, `toc`, `toc_scan` (a scan's toc on the GPU lane), `profile_search`, `assemble_chapter`, `book_metrics`, `eval_run`, `toc_eval`, `cleanup`, and `noop`, `noop_gpu` for tests of the queue; the list follows `SPECS` in `app/job_specs.py`; a recollection runs as `intake`, `metadata` or `toc` |
| lane | text | `gpu`, `cpu` |
| parent_id | fk jobs | book run → stage jobs → chapter jobs |
| run_id | fk runs | |
| book_id | fk books | the book a job works on, for book-level jobs and their children |
| options | jsonb | validated by a pydantic spec per type |
| status | text | `new`, `running`, `done`, `error`, `paused`, `cancelled` |
| attempts | int | spent by failures only; a deferral spends none |
| reclaims | int | times a running job was taken back from a worker that stopped answering |
| apply_since | timestamptz | backoff and deferral |
| waiting_because | jsonb | why a new job waits: `{kind, ...}`, e.g. `deferred` with its reason |
| code_hash | text | worker code hash that ran it |
| result, error | jsonb | |
| elapsed | real | |
| deferred_seconds | int | the deferral delays added up, so a job's wait is told apart from its work |
| created_at, updated_at | timestamptz | |

## evaluation_sets, evaluation_members

| field | type | notes |
|---|---|---|
| evaluation_sets.name | text unique | |
| evaluation_sets.targets | jsonb | SC-002 target (0.95) and the SC-011 margin, set by the owner after the first evaluation run |
| evaluation_members.set_id | fk | |
| evaluation_members.book_id | fk books | |
| evaluation_members.mode | text | `normal`, `bookmarks_off`, `as_scan` (FR-029, FR-049) |
| evaluation_members.best_profile_id | fk profiles | best known profile (SC-007) |
| evaluation_members.expected_metadata | jsonb | checked values per field, the reference for SC-010 |

## gates, evaluation_runs

| field | type | notes |
|---|---|---|
| gates.id | bigint | |
| gates.set_id | fk evaluation_sets | |
| gates.columns | jsonb | metric columns judged |
| gates.tolerance | jsonb | per column |
| gates.untouchable | int[] | member ids the change must not touch |
| gates.registered_at | timestamptz | must precede the run |
| evaluation_runs.gate_id | fk gates | |
| evaluation_runs.baseline_id | fk evaluation_runs | |
| evaluation_runs.rows | jsonb | per member: metrics, deltas, rules fired, output changed |
| evaluation_runs.result | jsonb | worse members with reasons, unexpected changes, passed or failed |

## State machines

Book stage (FR-041): `uploaded → metadata → toc → ready`; book-level stages, each producing a new
version (FR-052). Run stage: `profile → assembling → metrics → done`, starting from the current
versions. Any stage can go to `failed` and back to itself on resume.

Run status: `queued → running → done | needs_attention | failed | cancelled`. `needs_attention`
means every chapter is done or failed and at least one failed after its retries (FR-056); resume
reruns the failed chapters. `failed` and `cancelled` runs can be resumed into `running` in the
same `dir`.

Job status: `new → running → done | error`, plus `paused` and `cancelled`. Jobs end in `error`, runs
and chapters in `failed`; the two words are kept apart on purpose.

Chapter status: `pending → running → done | failed`; rerunning a chapter sets it back to
`pending`, then `book_metrics` recomputes (FR-044, FR-045).

## Validation rules from the spec

- Heading levels 1..6 in the document model; a writer rejects anything else (FR-004).
- A chapter's level comes from its toc entry; inner headings are relative to it (FR-043).
- Book numbers = sums of the chapters' words and sub-entries, with the worst chapters named; no verdict label (FR-045).
- A new knob option is selected only by profiles naming it; the evaluation run counts members whose
  output changed without selecting it (FR-016, FR-028).
