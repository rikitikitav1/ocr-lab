---

description: "Task list for PDF Book to Measured Markdown Bundle"
---

# Tasks: PDF Book to Measured Markdown Bundle

**Input**: Design documents from `specs/001-pdf-book-to-markdown/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: included. The constitution (Development Workflow) requires every check a principle names to be enforced by an automated test or a report field, and SC-005 names a kill-and-resume test.

**Organization**: grouped by user story in the spec's priority order P0 to P5 (labels US0 to US5).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: user story the task belongs to (US0 to US5)
- Paths are relative to the repository root, layout as in plan.md

---

## Phase 1: Done

What the stand does as of 2026-10-18; the work and the numbers are in the logs named.

- The stand: one compose command, a GPU lane held by one worker and a CPU lane for any, REST and MCP for every operation, an artifact per stage, runs that survive a killed worker.
- The catalogue: a PDF of one or several files becomes a book with metadata from the book itself, each field with its source.
- The structure: a tree of nodes from bookmarks, printed contents, chapter files, text-layer headings, numbering, labels or raster headings, scored on its own (structure_log, book_layout).
- The bundle: two engines, a referee per page against the text layer, the page layout's furniture, notes, captions and code, Markdown with images and a report of what was lost (elements_log).
- The quickstart runs end to end and the README follows the stand as built.

---

## Phase 2: The structure

The sources without word lists first, the tree's last step and the dictionaries.

- [ ] T179 A book with no bookmarks and no placed contents gets its structure from the headings of the whole book as the last try before one chapter (at most 100 pages) or "structure not recognised", which it reaches when no chapter level is found; read page by page (font size and weight from the layer, block height and type from MinerU on a scan), with repeated lines dropped; several independent level methods (height clusters, numbering vote, MinerU's own levels, a local model over the titles) are each scored against bookmarks, then an arbitration across them; a contents without page numbers is matched against the headings found; gated on text books with bookmarks read as rasters (7, 113, 1) before it takes any book; a reference manual is parts (its sections) over chapters (its pages), as on 55 (owner, 2026-10-12); built as the source `headings`, on by default as the last try before failing (the book knob `structure.from_headings` turns it off; more top entries than half the pages is no structure): the headings grouped by look, page-furniture typing not trusted (repeats and the running heads' size decide), the same entries as the measured probe on 20 books; headings before the end of a contents printed in the first 30 pages are cut (extras 118 to 53 on the 20, no chapter lost); a doc_title block stays a candidate up to 40 words; the third gate (47, 50, 66, 94) failed on every text book, the stage's own bookmarks-off structure no better on 47 and 50; open: the start of a book with no contents, edited volumes, a gate on unseen books
- [ ] T177 (in progress, closes with T191) The structure stops depending on word lists in config/structure.yaml: a printed contents page is found by its shape (numbered lines whose page numbers rise and reach the book's end) with the heading word only a hint, and chapter labels are found as a word repeated at the top of many pages with a rising number; gated by a shelf snapshot, only books the lists missed may move (owner, 2026-10-11) · first try failed its gate (18 books moved, covered ones among them) and was taken back; the mechanisms and the next pieces are in docs/experiments/2026-10-13_toc-without-words.md
- [ ] T191 Step 3 (left: the automatic level stored in the book metadata when the structure is collected, today computed as 0 at run start; text_layer.numbering.part and chapter and title_depth -1 gone, which closes T177): the engines read the nodes of the reading level (book metadata: an automatic level, 0 by default, set when the structure is collected, and the owner's level, empty by default, which wins), a node over 100 pages replaced by its own pages and its children, a leaf read whole; kind, text_layer.numbering.part and chapter and title_depth -1 gone, the front matter's service role kept per FR-042, FR-064, FR-008 (contradicts) · gate: pieces on the shelf as probed (5406 pieces; counted as multisets, 3596 of today's 3825 units kept and 84 of 122 books identical; 417 pages today's units never read added on 67, 77, 95, 71, 90, 73; leaves over 100 pages only on 1, 18, 26, 71, 104, 110, 120, 125); closes T177
- [ ] T186 A level whose pins split in style is reported back to the structure as a suspect level, once service entries and chapter numbers larger than their titles are out of the count per FR-063 (missing)
- [ ] T197 A contents without indents keeps "Глава 1." above "1.1." by the word the book repeats before its numbers (2, 11, 53) per FR-008 (partial)
- [ ] T198 Book 8: a contents heading below imprint lines is told from a part title by shape per FR-008 (partial) · after P1: one book, a knob (owner: no per-book knobs for now)
- [ ] T199 A contents continuing past the window counts only in-range page numbers, as the page rule does, measured alone per FR-008 (partial)
- [ ] T205 The contents rows T204 left: 107's printed wrap "…Income/Consumption" + "Tax", 73's "Part V." alone on its line, 104's titles ending "sect. 1" or "Art. 28" read as page numbers per FR-008 (auditor 113) · gate: a shelf snapshot, only the named books move · after P1: one book, a knob (owner: no per-book knobs for now)
- [ ] T211 A label ending with a full stop ("Глава 1.") over the next title stays with its node at the boundary cut, gated like T209 per FR-042 (partial)
- [ ] T184 Scans get a page layout from MinerU's boxes (three-line shape of probe 3) per FR-063 (missing)
- [ ] T187 Book 120's guide words with the folio mid-line: a book knob if it stays one book per FR-063 (partial) · after P1: one book, a knob (owner: no per-book knobs for now)
- [ ] T201 Step 0 for dictionaries: full runs of 120 to 126 and 128 on the defaults, defects in one table by mechanism, then a book known as a dictionary from its subject (a book knob overrides) and its letters as top nodes per FR-050 (missing)
- [ ] T153 A structure evaluation set (`POST /eval/structure`, beside `hips`) of a seeded sample of about 50 ICDAR/INEX Book Structure Extraction 2013 books, scored by `app/evaluation/structure_gold.py` and by the set's own title-based and link-based scorers per FR-058 (missing)

---

## Phase 3: Reading and assembly

- [ ] T260 Each element of a book lives in one module under `app/elements/`: how the book sets it (learned from the book's own pages), how it is set into the blocks, how the report measures it; running heads and folios, footnotes, captions, code and a chapter's contents block move there first, `assembly/passes.py` keeps only the order of the passes, and formulas and asides join as elements; output byte-identical on the 47 reassemblies (owner 2026-10-18: first after the PR)
- [ ] T252 (the asides, after P1) A listing's callouts become an attribute of its code block, margin notes and rubrics are kept as notes; line numbers, contents lines and margin running heads stay dropped per FR-006, FR-063 (partial) · the footnotes half closed for P1 (Phase 1)
- [ ] T151 keep MinerU's all-caps boxes out of the headings as a book knob in app/assembly/passes.py, measured on book 9 (13 long headings) per Constitution IV (partial) · parked by the owner (no per-book knobs for now); measured offline: heading_max_words 12 turns 19 headings of book 9 into paragraphs, all boxed tasks, long_headings 13 to 0, lost and subs unchanged; patch kept outside the repo
- [ ] T158 Break a referee tie in app/assembly/referee.py per_page without favouring Docling by list order, gated on every text book with out_of_order as a column per FR-045 (partial)
- [ ] T159 Flag an engine page that comes back empty on an inked page, and try a pypdfium2 render of MRC pages as a book knob on book 9 per FR-031 (partial) · the pypdfium2 Docling backend measured worse in rag-lab as a text extractor (owner); here only the render of recognised (scan, garbled) ranges is at stake, or pages rendered by us and handed over as images, docling-parse kept on layer pages; after the rag-lab comparison, in own images
- [ ] T161 Count recognised pages where one engine is empty apart from disagreement in passes.recognised, and take Docling's text where MinerU is empty and Docling passes a sanity check, under its own gate per FR-032 (partial)
- [ ] T162 Build the hand-checked text gold of 20 to 30 pages from Russian scans on the shelf, checked by the owner, and score recognised text against it per FR-049 (missing)
- [ ] T172 (after the non-invasive tasks) The intake probe reports the layer's defect signs as numbers in the book's text_layer, no verdict, backfilled for every book on the shelf and listed in docs/books.md: share of one- and two-letter words, share of letter-spaced rows, PDFium line breaks inside a word on one row, alphabet runs, page image kinds (JPEG, JBIG2, masked), made_with; seen on 110, 11, 8, 9 per FR-045 (missing)

---

## Phase 4: User Story 3 - The stand assembles the book's profile (Priority: P3)

**Goal**: the stand probes a book, picks a preset, searches knob values on sampled chapters, and keeps the best profile with evidence for every value. Built: T081, the profile doors and their test (`GET /knobs`, `GET /presets`, `GET /profiles/{id}`, `POST /profiles/{id}/derive`, tests/doors/test_profiles.py).

- [ ] T080 [P] [US3] Create `tests/stages/test_profile_search.py`: probes choose a preset; candidates scored with the report's chapter checks; the kept profile is no worse than the preset on the sampled chapters; every candidate stored with decision and reason; a search killed after some candidates and resumed scores only the rest (FR-013, FR-021, FR-023)
- [ ] T082 [US3] Write `db/migrations/20261009000002_profile_candidates.sql` for `profile_candidates` (`search_job_id`, `profile_values jsonb`, `sample_chapters int[]`, `scores jsonb`, `decision` in (`kept`, `dropped`), `reason`) and its table in `app/orm/catalogue.py`; regenerate `db/schema.sql`
- [ ] T083 [P] [US3] Fill `config/knobs.yaml` with the knob groups: structure sources and order, chapter title, section heading, code block, note or sidebar, table, caption, running head, verse (line breaks kept, dialogue dashes kept as text), tables and figures continued on the next page, images, engine per range, chunk page count, model provider per step, search budget (number of candidate profiles scored); and `config/presets/*.yaml` (default, bookmarked text PDF, scan, picture-led book)
- [ ] T084 [P] [US3] Implement probes in `app/probes/`: `layout.py` (columns, monospace share, image share, font profile), `scan.py` (pages without a layer), `matter.py` (front and back matter), each returning the knobs worth searching and a preset hint
- [ ] T085 [US3] Implement `app/stages/profile_search.py`: run probes, pick a preset, sample chapters (first, longest, one with code, one with figures), coordinate search over flagged knobs within the budget knob (candidates scored), score with `app/quality/chapter.py`, store every candidate, freeze the best into a profile with evidence (research R10)
- [ ] T134 [US3] Make profile search resumable in `app/stages/profile_search.py`: each scored candidate is written as an artifact with its input hash (book, profile values, sample chapters, engine builds, code hash) next to its `profile_candidates` row, and a resumed search finds them with `find_done` and scores only the rest (Constitution VIII, FR-021, FR-023)
- [ ] T086 [US3] Register job `profile_search` before chapter assembly in `app/job_handlers/run.py` when the run asks for `search: true`
- [ ] T087 [US3] Door `GET /runs/{id}/candidates` with its tool (FR-015), after T082 and T085 · done: `GET /knobs`, `GET /presets`, `GET /profiles/{id}`, `POST /profiles/{id}/derive` in `app/api/v1/knobs.py`; a searched value names the artifact of the measurement that chose it, opened through the run's artifact door (SC-006); the report names the candidates the search tried and why each was kept or dropped (moved from T068)

---

## Phase 5: User Story 4 - Evaluation set and gated shared changes (Priority: P4)

**Goal**: evaluation sets with modes, gates registered before runs, per-member comparison naming every book that got worse and every unexpected change. Built ahead of it: `POST /eval/structure` (sets `bookmarks_off`, `contents_off`, `hips`) and `POST /eval/elements`.

- [ ] T088 [P] [US4] Create `tests/stages/test_evaluation.py`: a gate registered after the run starts is refused; worse members listed with deltas and reasons; a member whose output changed although no changed rule fired is counted separately (FR-027, FR-028)
- [ ] T089 [P] [US4] Create `tests/stages/test_eval_modes.py`: `bookmarks_off` scores other structure sources against bookmarks (FR-029); `as_scan` ignores the text layer and scores recognised text against it (FR-049)
- [ ] T090 [US4] Write `db/migrations/20261009000003_evaluation.sql` for `evaluation_sets` (`name` unique, `targets jsonb`: SC-002 and SC-011 targets, both 1.0), `evaluation_members` (`mode` in (`normal`, `bookmarks_off`, `as_scan`), `best_profile_id`, `expected_metadata jsonb` checked values per field), `gates` (`columns`, `tolerance`, `untouchable int[]`, `registered_at`), `evaluation_runs` (`baseline_id`, `rows`, `result`) and tables in `app/orm/evaluation.py`; regenerate `db/schema.sql`; its compare scores SC-002 with `bookmarks_off` and SC-011 on the scanned members against the set's targets
- [ ] T091 [US4] Record rules fired per chapter in `app/stages/assemble.py` and `report.json` `knobs_applied`, so changes can be attributed per member
- [ ] T092 [US4] Implement `app/evaluation/sets.py` and an `as_scan` run option beside `bookmarks_off`, moving `bookmarks_off` out of `app/evaluation/structure_run.py` into one modes module that members reuse (FR-029, FR-049)
- [ ] T093 [US4] Implement `app/evaluation/compare.py`: per-member metric deltas against the baseline, worse members with reasons against gate tolerance, unexpected-change count, metadata correctness against `expected_metadata` seeded from `eval/gold/metadata.yaml` (SC-010), `chapter_below_own_section` and `max_level` per member (SC-003), registry size (knobs, options) and options added since the baseline (Development Workflow), gate passed or failed; update `best_profile_id` when a member beats it (SC-007, SC-008)
- [ ] T094 [US4] Register job `eval_run` in `app/job_handlers/evaluation.py` and doors with tools in `app/api/v1/eval.py`: `POST /eval/sets`, `GET /eval/sets/{id}`, `POST /eval/gates`, `POST /eval/runs`, `GET /eval/runs/{id}`
- [ ] T095 [US4] Create the first evaluation set from research R15 (22 bookmark books, three scans, dannyh, two text books as scans) with `scripts/seed_eval_set.py`, filling `expected_metadata` from `eval/gold/metadata.yaml` (books with `checked: true`, matched by sha256 prefix) (SC-010)
- [ ] T135 [US4] Owner's decision: the novel, children's book, school textbook and poetry collection that join the evaluation set before its first run, added through `scripts/seed_eval_set.py` (FR-050, research R15)

---

## Phase 6: Formulas as a layout element (owner, 2026-10-17)

The survey: `~/working_docs/projects/ocr-lab/notes/formulas_survey.md`. Formulas are found and described first; the Markdown does not change until a step below says so, each through its own gate.

- [ ] T225 The adapters keep a formula's box and kind: MinerU `equation` with its bbox, `equation_inline` as an inline formula placed by the layer, Docling `formula` with its prov box and `orig`; `Formula` carries kind (display or inline), the engine's LaTeX and the layer text under it per FR-005, FR-063 (missing) · gate: every bundle byte-identical on the 47 books of the raw run
- [ ] T226 The layer reader returns each glyph's face name, so a box can be measured for math faces and math characters per FR-063 (missing) · gate: the layer text and every measure unchanged on the shelf
- [ ] T227 A formula element in the page layout, learned per book: the math face family, the numbering style at the right margin ("(3.2)", "[7]"), display lines centred or not, sizes against the body; each formula placed with its parameters (page, box, kind, engines that saw it and their boxes' overlap, each engine's LaTeX, layer text, math-face share and names, math-character share, U+FFFD and private-use count, number) per FR-063 (missing)
- [ ] T228 Step 0 for formulas: the element collected over the shelf, a table per book of formulas by kind and by which signal holds them, and the junk by mechanism (code read as formulas on 18, pictures and tables on 110, ordinals and chemistry inline on 83 and 89, syntax diagrams on 5, a reference read as a formula on 19) before any rule changes the output per FR-063 (missing) · numbers in an experiment
- [ ] T229 Our MinerU build is checked for the newer layout classes (`display_formula`, `inline_formula`, `formula_number`) and scores; if missing, what upgrading would cost is measured, not done (owner's decision)
- [ ] T230 Formula recognition is chosen by a measurement, not adopted: PP-FormulaNet_plus-M and Docling CodeFormulaV2 on the same crops of display formulas from 23, 58, 19 and a Russian book, against a small hand-checked gold (owner checks), scored by CDM and by the layer text where the book has one (owner's decision)
- [ ] T231 The formula scheme drawn like docs/diagrams/code.drawio.svg from what T228 measured: which signals hold formulas, which catch junk, where each engine's box and LaTeX enter (moved from T147)

---

## Phase 7: User Story 5 - An external agent grows the knob registry (Priority: P5)

**Goal**: an external developer agent can find a defect, add a knob, and prove it changes nothing for books that do not select it, using only doors and code. Built: T098, `config/knobs.yaml` validated at the API and worker start (tests/unit/test_knobs.py).

- [ ] T096 [P] [US5] Create `tests/stages/test_new_knob_isolation.py`: a dummy option registered but selected by no profile leaves every bundle byte-identical (FR-016)
- [ ] T097 [US5] Extend `GET /knobs` in `app/api/v1/profiles.py` with each option's implementation name and the probe, and add `POST /eval/runs` option `members` to run a subset (doors for the agent loop)
- [ ] T099 [US5] Add a section "Adding a knob" to `README.md`: where options live, how to register, how to prove isolation with an evaluation subset run
- [ ] T100 [US5] Acceptance: through MCP only, add one real knob for a defect from the starting list (rag-lab-intake findings), show the improved report and the isolation run; keep the trial eval runs and their results as stand artifacts and record the result, with links to them, in `~/working_docs/projects/ocr-lab/notes/` (Constitution VIII)

---

## Phase 8: Polish

- [ ] T103 [P] Record seconds and GPU seconds per stage and chapter in `report.json` `seconds` and check they are filled for the whole evaluation set (research R14)

FR-030 has no task here: this feature ships one format. When a second format arrives, a full evaluation-set run showing byte-identical Markdown bundles is its regression proof.

---

## Dependencies & Execution Order

- Phase 1 is done.
- Phases 2 and 3 are tuning on the shelf; each change goes through its own gate, registered before its run.
- Phase 5 after Phase 4's profiles (`best_profile_id`); Phase 7 after Phase 5 (isolation is proven with evaluation runs).
- Phase 6 any time; its steps change no Markdown until their gate.
- The comparison with rag-lab on its questions starts once Phases 2, 3 and 6 are closed (owner, 2026-10-18): ocr-lab prepares the sources, rag-lab only reads Markdown, HTML and the like.
- Within a phase: tests first, migrations before stages, stages before handlers, handlers before doors; every door ships with its MCP tool (the parity test enforces it).
