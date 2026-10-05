# Feature Specification: PDF Book to Measured Markdown Bundle

**Feature Branch**: none (the repository goes under git after the implementation plan)

**Created**: 2026-10-05

**Status**: Draft

**Input**: User description (assembled from the constitution session, the command was run without
arguments): "A book in electronic form (PDF) becomes structured Markdown whose sections match the
book. Later other e-book formats come in and other structured formats go out, for example the
Docling format for RAG. Quality is always measured. The accent is on autonomy: feed a book, pick a
format, get Markdown of measured quality plus a folder of images linked from the document.
Processing is driven by a nested set of per-book knobs (where the table of contents comes from,
how a code block, a note, a table, a chapter title is recognised); presets of knobs may exist, but
every book gets its own profile. The agent's jobs are to assemble the knobs for a book and to learn
to make new knobs on its own. Artifacts remain for every stage, and an interrupted build restarts
painlessly from the last saved point." Added by the owner: "Before all that comes P0: the stand
under Docker Compose with its own database, reusing what rag-lab has already downloaded; at this
stage a submitted file yields its metadata (author, edition, year, language, text layer, subject,
publisher), maybe the clean table of contents too, as it turns out." Scanned PDFs are in scope.

## Clarifications

### Session 2026-10-05

- Q: Who is "the agent" that picks knobs and designs new ones? → A: Hybrid. Profile assembly runs
  inside the stand, as much as possible mechanical (probes, search, measurements), with a model
  only where no probe covers the step; new knobs are designed by an external developer agent
  working through the stand's doors and the code. An agent layer inside the stand may come later;
  it would use the same doors.
- Q: Through which doors do the owner and an external agent submit books, watch stages and read
  reports? → A: An HTTP API with MCP tools over it; no web interface for now, maybe later.
- Q: How many books does the stand process at once? → A: A job queue; non-GPU stages run in
  parallel across books, one job at a time on the GPU (as in rag-lab, open to improvement).
- Q: How is recognition quality measured on scanned pages with nothing to compare against? → A:
  Gold from text-layer books run as scans, plus agreement of two engines and dictionary word share
  on real scans.
- Q: How do chapter verdicts add up to the book verdict? → A: Worst of the chapter verdicts and
  the whole-book checks; one `bad` chapter makes the book `bad`.
- Q: May the owner set a metadata field by hand? → A: Yes, as source `manual` overriding found
  values; content and table of contents are never edited by hand.
- Q: On a second run of a book, are metadata and the table of contents collected again or reused?
  → A: They belong to the book and are versioned; a run uses the current versions and records
  them; recollection is explicit or triggered by a change in their knobs or source code, and
  creates new versions.
- Q: Which bundle is the book's result when it has several runs? → A: The best finished run: by
  verdict (`ok` over `dirty` over `bad`), then by structure metrics, then the latest.
- Q: What if a book comes in several PDF files (volumes, parts, chapters)? → A: A book split into
  files (parts, chapters) is submitted as several files in order and becomes one book with one
  bundle. Volumes are separate books, each with its own bundle, linked in the catalogue through
  the metadata fields series and volume.
- Q: What may an explicit cleanup remove? → A: Two separate commands: deleting a run the owner
  names, for any reason; and a space-saving cleanup of heavy intermediates of runs that are not the
  book's result and of dropped profile candidates, keeping reports, profiles, measurements, model
  calls and result bundles.
- Q: What happens when a chapter still fails after all retries? → A: The other chapters finish,
  the run waits for attention without book metrics or bundle, visible through the doors (run
  status, jobs, `wait_job` returning with the error); after an agent or the owner looked into it,
  only the failed chapters are rerun, then metrics and bundle.
- Q: How many retries does a stage get? → A: 3 to 5, set per stage in configuration; then stop and
  wait for attention. A tool-call budget and its accounting come later.
- Q: How is the table-of-contents stage checked before whole books can be assembled? → A: On its
  own, against external gold sets (HiPS, LongDocBench when reachable) and bookmarks.
- Q: Which pages are read as title pages, and can the owner point at the contents pages? → A: The
  first 20 and the last 20 by default, a book knob; the printed contents pages can be given as page
  ranges at submission or later.

## User Scenarios & Testing *(mandatory)*

### User Story 0 - Stand up the stand and catalogue a book (Priority: P0)

The owner brings the stand up with one command. It has its own catalogue and reuses the engines,
models and books already downloaded for rag-lab instead of fetching them again. The owner submits
a PDF, and the stand records the book in its catalogue with what it could learn about it: title,
authors, edition, year, language, publisher, ISBN, subject, page count, whether pages carry a text
layer, whether bookmarks and printed contents pages exist, and, if it comes cheaply, the table of
contents itself.

**Why this priority**: every later step reads this record (which preset fits, which engine, which
table-of-contents sources exist), and nothing runs without the stand.

**Independent Test**: on a clean machine that already holds the rag-lab downloads, bring the stand
up, submit three books (one with bookmarks, one without, one scanned), and read their catalogue
records; no engine or model is downloaded again, and each field shows where its value came from.

**Acceptance Scenarios**:

1. **Given** a machine with the rag-lab downloads, **When** the owner brings the stand up,
   **Then** all its services start with one command and no engine image or model weight already
   present is downloaded again.
2. **Given** a submitted PDF, **When** intake finishes, **Then** the catalogue holds a record with
   every metadata field either filled, with its source and confidence, or marked unknown.
3. **Given** a scanned PDF, **When** intake finishes, **Then** the record says which pages have no
   text layer, and title, authors and language are still filled where the title pages show them.
4. **Given** a file already in the catalogue, **When** it is submitted again, **Then** the stand
   recognises it as the same book and does not create a second record.
5. **Given** a book split into several PDF files, **When** the owner submits them together in
   order, **Then** the catalogue holds one book whose pages run across the files in that order.
6. **Given** a book with bookmarks or printed contents pages, **When** intake finishes, **Then**
   the record says which table-of-contents sources exist, and holds the extracted table of
   contents if intake could extract it.

---

### User Story 1 - Feed a PDF, get a measured Markdown bundle (Priority: P1)

The owner hands a PDF book to the stand and asks for Markdown. Without any further action they get
a bundle: the Markdown document with the book's chapters and sections at the right levels, an
images folder linked from the document, the profile that was used, and a quality report with a
verdict.

**Why this priority**: this is the product. Every other story improves or protects this one.

**Independent Test**: convert a PDF that has bookmarks; open the bundle; check that chapters in
the document match the bookmarks, every image link opens, and the report carries a verdict with
reasons.

**Acceptance Scenarios**:

1. **Given** a PDF with a text layer and bookmarks, **When** the owner submits it with format
   Markdown, **Then** a bundle appears with the document, `images/`, the profile and the report,
   and no question is asked during the run.
2. **Given** the finished bundle, **When** the owner moves the bundle directory elsewhere, **Then**
   every image link in the document still opens.
3. **Given** a book whose structure the stand could not recover, **When** the run ends, **Then**
   the bundle is still produced and the verdict is `dirty` or `bad`, naming the defects and the
   knobs that were tried.
4. **Given** a book, **When** the report is read, **Then** it shows chapters found against the
   table of contents, heading levels per table-of-contents source, text fidelity against the PDF
   text layer, image and link counts, and the verdict.
5. **Given** a book in progress, **When** the owner looks at it, **Then** they see which stage it
   is in (upload, metadata, table of contents, chapter assembly, book metrics) and, during chapter
   assembly, which chapters are done, with their own verdicts.
6. **Given** a finished book with one `bad` chapter, **When** the owner (or an external agent) changes the
   knobs for that chapter and reruns it, **Then** only that chapter is reassembled and the book
   metrics are recomputed.

---

### User Story 2 - Every stage leaves an artifact and a broken run resumes (Priority: P2)

Each stage of a run writes its result as a file. If a run is interrupted (crash, kill, reboot,
engine timeout), restarting it continues from the last completed stage or chunk instead of
starting over, and the final bundle is the same as from an uninterrupted run.

**Why this priority**: book runs are long (hundreds of pages, engine calls), profile search
(User Story 3) multiplies them, and a defect can only be traced if every intermediate step is on
disk.

**Independent Test**: start a run on a long book, kill it in the middle of conversion, restart it;
check that finished stages were not redone and the bundle matches an uninterrupted run of the same
book and profile.

**Acceptance Scenarios**:

1. **Given** a finished run, **When** the owner opens its run directory, **Then** there is an
   artifact for every stage: probes, table of contents per source and reconciled, raw engine
   output per chunk, the document model before and after each rule, the writer output, metrics.
2. **Given** a run killed mid-stage, **When** it is restarted, **Then** completed stages are
   reused, the interrupted stage is redone from its start, and no half-written artifact is
   treated as complete.
3. **Given** a finished stage whose inputs, profile or engine versions have changed since, **When**
   the run is resumed, **Then** that stage and everything after it are redone.
4. **Given** an earlier run of the same book, **When** a new run starts, **Then** the earlier run
   directory is left untouched.

---

### User Story 3 - The stand assembles the book's profile (Priority: P3)

Instead of one fixed setting for all books, the stand probes the book, picks a preset, tries
candidate values for the knobs that matter for this book, measures each candidate with the same
metrics the report uses, and keeps the best profile. The owner can read why each value was chosen.

**Why this priority**: books differ too much for one setting (heading styles, code, sidebars,
running heads). Without per-book profiles the P1 bundle is right only for "typical" books.

**Independent Test**: run two books with different layouts; their resolved profiles differ in at
least the knobs the probes flagged, each chosen value names the measurement that chose it, and the
report of each is no worse than the same book run on its preset alone.

**Acceptance Scenarios**:

1. **Given** a book, **When** the stand assembles its profile, **Then** every knob value in the
   profile records its source (preset, probe, or search) and its evidence.
2. **Given** the stand tried several candidate profiles, **When** the owner opens the run, **Then**
   every candidate, its measurement, and the reason it was kept or dropped are there.
3. **Given** the owner edits a knob in a book's profile by hand, **When** the book is rerun with
   that profile, **Then** the edit is applied and stamped in the report as a manual override.

---

### User Story 4 - Evaluation set and gated shared changes (Priority: P4)

The owner keeps a set of evaluation books. A change to shared behaviour (a preset, the code behind
a knob option, a metric) is run over the whole set against a gate registered before the run, and
the result names every book that got worse and why.

**Why this priority**: without it, a fix for one book silently breaks others, which is the main
lesson carried over from rag-lab.

**Independent Test**: register a gate, run the set before and after a deliberate change, and get a
comparison that lists each book whose metrics moved, the direction, and whether it falls within
the registered tolerance.

**Acceptance Scenarios**:

1. **Given** a registered gate (columns, tolerance, books the change must not touch), **When** the
   evaluation run finishes, **Then** the result lists every book that got worse with its metric
   deltas, and the gate is marked passed or failed.
2. **Given** a change whose rule did not fire on a book, **When** that book's output changed
   anyway, **Then** the result counts it separately as an unexpected change.
3. **Given** books with PDF bookmarks in the set, **When** the set runs with bookmarks switched
   off, **Then** the other table-of-contents sources are scored against the bookmarks.

---

### User Story 5 - An external agent grows the knob registry (Priority: P5)

When no existing knob or option fixes a defect the report shows, an external developer agent designs a new knob or a
new option, implements it, and measures it on the books that showed the defect. The new knob is
off for every book whose profile does not select it.

**Why this priority**: the long-term goal is a stand that learns new kinds of books on its own,
but it depends on stories 1 to 4 being in place to measure anything.

**Independent Test**: take a book with a known defect no knob covers; let the agent propose and
add a knob; check that the book's report improves, and that the evaluation set shows no change on
books that do not select the new knob.

**Acceptance Scenarios**:

1. **Given** a defect no registered knob addresses, **When** the agent adds a knob, **Then** the
   registry holds it with its options, a one-line explanation and the probe that tells whether it
   fits a book.
2. **Given** a new knob, **When** the evaluation set runs, **Then** no book whose profile does not
   select it changes output.
3. **Given** a new knob, **When** it is added, **Then** its design, trial runs and measurements are
   kept as artifacts.

---

### Edge Cases

- Non-technical books: a novel with chapters as the only headings, a children's primer where
  pictures carry most pages and fonts are large, poetry where line breaks are content, dialogue
  lines in fiction that start with a dash.
- A PDF with no text layer (scanned book) or with a mix of scanned and text pages.
- A book in several files: each file with its own bookmarks, own front matter or own printed
  contents; a scan and a text file mixed in one book.
- A PDF with bookmarks that are wrong, partial, or flatter than the real structure.
- A book with no bookmarks, no printed contents and no numbering, where only typography is left.
- Running heads, footers, sidebars (TIP, NOTE) and captions styled like headings.
- Chapter titles in capitals without numbers; "Chapter N:" prefixes; parts above chapters.
- Very long chapters with no internal sections, and books over 1000 pages.
- Duplicate pages, blank pages, front and back matter (index, bibliography, contents pages).
- Images that are decorative (logos on every page) versus figures; figures split across pages.
- Code listings broken across pages, tables continued on the next page.
- An engine that hangs or crashes on a specific page range.
- The disk filling up mid-run; a resume after the profile or engine version has changed.
- The stand's model provider unavailable or rate-limited during intake or profile search.

## Requirements *(mandatory)*

### Functional Requirements

**Conversion and bundle**

- **FR-001**: The stand MUST accept a PDF book, as one file or several files in order, and a
  target format, and produce a bundle without any human step during the run.
- **FR-002**: For format Markdown, the bundle MUST contain the document, an `images/` folder, the
  resolved profile and the quality report.
- **FR-003**: Every image link in the document MUST resolve inside the bundle, and every file in
  `images/` MUST be referenced at least once; the report MUST count both.
- **FR-004**: Headings MUST use levels 1 to 6 only, with the book title at level 1 and chapters at
  level 2 unless the book has parts.
- **FR-005**: Code blocks, tables and lists MUST keep their type in the output; code MUST be taken
  from the PDF text layer where one exists.
- **FR-006**: Running heads, footers, sidebars and captions MUST NOT be output as headings;
  duplicate pages MUST be removed and reported.
- **FR-007**: Decorative images repeated on many pages MUST be distinguishable from figures and
  MUST NOT be emitted as figures.

**Structure**

- **FR-008**: The table of contents MUST be gathered from every available source (bookmarks,
  printed contents pages, numbering in the text, typography, a model reading the contents pages,
  external book catalogues and publisher sites) and reconciled into one.
- **FR-009**: Each heading MUST record which source decided its level, and the report MUST count
  headings per source.
- **FR-010**: Heading levels MUST be decided across the whole book, never per processing chunk.

**Profile and knobs**

- **FR-011**: The stand MUST keep a registry of knobs, grouped by question, where each knob has its
  options, a one-line explanation, and a probe or metric that tells whether a value fits a book.
- **FR-012**: The stand MUST support presets as named partial profiles; a book's profile MUST be
  able to override any knob of its preset.
- **FR-013**: The stand itself MUST assemble a profile for each book by probing it, choosing a
  preset and searching candidate knob values, measured with the same metrics the report uses. As
  much of this as possible is mechanical (rules, probes, measurements); a model is called only for
  steps no mechanical probe covers, such as reading contents pages.
- **FR-014**: Each knob value in a resolved profile MUST record its source (preset, probe, search,
  manual override) and its evidence.
- **FR-015**: The owner MUST be able to edit a book's profile and rerun the book with it.
- **FR-016**: An external developer agent MUST be able to add a new knob or option to the registry
  when no existing one fixes a reported defect, working through the stand's doors (to read reports
  and artifacts, run books and evaluation sets) and through the code; a new knob MUST NOT change
  the output of books whose profiles do not select it.

**Quality**

- **FR-017**: Every run MUST produce a machine-readable report and a short human-readable summary.
- **FR-018**: The report MUST cover structure against the table of contents (chapters found,
  levels, order), text fidelity against the PDF text layer, heading level sanity, image and link
  integrity, and a verdict `ok`, `dirty` or `bad` with reasons.
- **FR-019**: The verdict MUST NOT be `ok` when chapters are missing, a chapter sits below its own
  sections, or a long chapter has lost all internal sections that the table of contents shows.

**Artifacts and resume**

- **FR-020**: Every stage of a run MUST write its output as an artifact that names its stage,
  inputs, resolved profile and engine versions.
- **FR-021**: The stand's profile search MUST be kept: every candidate, its measurement, and why it
  was kept or dropped.
- **FR-022**: A stage MUST count as done only when its artifact is completely written.
- **FR-023**: An interrupted run MUST resume in its own run directory from the last completed
  stage or chunk without manual cleanup, reusing a finished stage only if its inputs, profile and
  engine versions are unchanged.
- **FR-024**: A resumed run MUST produce the same bundle as an uninterrupted one on deterministic
  stages.
- **FR-025**: A new run MUST NOT overwrite an earlier run; artifacts MUST be removed only by one of
  two explicit commands:
  - deleting a run the owner names, with all its artifacts; if it was the book's result, the
    result moves to the next best finished run (FR-053);
  - a space-saving cleanup that removes heavy intermediates (raw engine output, the document
    model after each rule) of runs that are not the book's result and of dropped profile
    candidates. Reports, profiles, measurements, model calls and the result bundle are never
    removed by it, and it can show what it would remove and how much space that frees before
    doing it.
- **FR-026**: Model calls MUST record the model and its parameters, and their outputs MUST be kept
  so a rerun reproduces them.

**Evaluation**

- **FR-027**: The owner MUST be able to keep an evaluation set of books and run the whole set
  against a gate registered before the run (columns, tolerance, books that must not be touched).
- **FR-028**: An evaluation result MUST list every book that got worse with its metric deltas and a
  reason, and separately count books whose output changed although the change did not fire on
  them.
- **FR-029**: The evaluation MUST be able to switch bookmarks off and score the other
  table-of-contents sources against them.

**Formats**

- **FR-030**: Adding a new input or output format later MUST NOT change the output of existing
  formats; this feature ships PDF in and Markdown out only.

**Scanned pages**

- **FR-031**: Pages without a text layer, whether a whole scanned book or single pages in a mixed
  one, MUST be recognised and converted like text pages, with the same structure and bundle rules.
- **FR-032**: For pages without a text layer the report MUST measure recognition quality, per page
  range and separately from text fidelity on text pages, by agreement between two recognition
  engines on the same pages and by the share of dictionary words in the book's language (plus
  engine confidence where an engine gives it).
- **FR-049**: The evaluation set MUST include text-layer books run as scans (text layer ignored),
  whose recognised text is scored against the text layer; this calibrates the measures of FR-032.
- **FR-033**: The recognition engine for a book or page range MUST be a knob in the profile.

**Genre**

- **FR-050**: Shared behaviour MUST NOT assume a genre: rules for code, sidebars, formulas, verse or
  picture-led pages apply only when the book's profile selects them, and a book with none of these
  goes through the stand with the same guarantees as any other.

**Stand and intake**

- **FR-034**: The stand MUST start with one command and keep its own catalogue of books, runs,
  profiles and evaluation results, separate from rag-lab's.
- **FR-035**: The stand MUST reuse engines, model weights and source books already downloaded for
  rag-lab rather than downloading them again.
- **FR-036**: On submission, the stand MUST identify the file by content, so the same book
  submitted twice maps to one catalogue record. Two editions of a work are two different books,
  and records are never merged by title or author.
- **FR-037**: Intake MUST collect, per book: title, authors, edition, year, language or languages,
  publisher, series and volume number, ISBN, subject, page count, text layer presence per page,
  presence of bookmarks and of printed contents pages. The year is that of this edition or
  translation. Required for every book (owner's rule): title, authors, language, subject, pages.
  Sought everywhere, by title and author when there is no ISBN, and taken from a title search only
  when exactly one edition matches: publisher, year, ISBN. Optional fields, which only a translation has and whose absence is not a gap
  (SC-010): translators, illustrators, original title, original year, original ISBN, and related
  editions: other editions of the same book found on the web (ISBN, publisher, year, format, link),
  kept apart so the main fields describe the file in hand.
- **FR-038**: Each metadata field MUST record its value, its source (file metadata, title pages,
  external book catalogue, model reading the pages) and a confidence. Intake MUST try every
  source before giving up on a field; a field marked unknown MUST list the sources tried, and a
  field the stand could not determine MUST NOT be guessed silently.
- **FR-051**: The owner MUST be able to set a metadata field by hand; the value gets source
  `manual`, overrides values found by the stand, keeps the found values in its evidence, and is
  marked as manual in the report. This is the only hand edit the stand accepts: book content and
  the table of contents are never edited by hand.
- **FR-039**: Intake SHOULD extract the table of contents when a source for it is found; when it
  cannot, the record says which sources exist and extraction is left to conversion.
- **FR-040**: Intake MUST leave its own stage artifacts and be resumable like any other stage.

**Stages and chapters**

- **FR-041**: A book MUST go through these stages in order: upload, metadata, table of contents
  (search across sources, reconciliation, filtering of non-chapter entries), profile, chapter
  assembly, book metrics. Each stage has a status the owner can see.
- **FR-042**: Chapters MUST be the unit of assembly: each chapter is assembled on its own, with
  its own checks, its own verdict and its own artifacts.
- **FR-043**: Chapter boundaries and chapter levels MUST come from the table-of-contents stage;
  levels inside a chapter are set relative to the chapter's level, so FR-010 holds.
- **FR-044**: A single chapter MUST be re-assemblable on its own, with knobs overridden for that
  chapter only, without redoing the other chapters.
- **FR-045**: Book metrics MUST be computed from the chapter results plus whole-book checks
  (chapters against the table of contents, duplicates across chapters, image and link integrity),
  and recomputed whenever a chapter is redone. The book verdict is the worst of the chapter
  verdicts and the whole-book checks: one `bad` chapter makes the book `bad`, and the report names
  the chapters that set it.
- **FR-046**: Resume MUST work at chapter granularity: an interrupted chapter assembly continues
  with the chapters not yet done.
- **FR-056**: A chapter that still fails after all retries MUST NOT stop the other chapters. When
  every chapter is done or failed and at least one failed, the run MUST wait for attention: no book
  metrics and no bundle yet, the failed chapters and their errors visible through the doors, and a
  waiting `wait_job` returns with them. Resuming the run reruns only the failed chapters, then book
  metrics and the bundle.
- **FR-057**: Each stage MUST have its own retry budget (3 to 5 attempts), set per stage in
  configuration; when a stage spends it, the stage stops and its part of the run waits for
  attention as in FR-056. A budget for tool and model calls and their accounting come later.
- **FR-058**: The table-of-contents stage MUST be measurable on its own, before chapter assembly
  exists: against external gold sets (HiPS legal textbooks; LongDocBench once its data is
  reachable) and against bookmarks with bookmarks switched off, reporting entry recall and
  precision, level agreement and tree similarity per book.
- **FR-059**: Book-level knobs MUST be settable at submission and changed later, each with a default
  in configuration: the title-page window for metadata (default the first 20 and the last 20
  pages) and the printed contents pages given by hand as page ranges. A change takes effect at the
  next collection of metadata or the table of contents.
- **FR-060**: Every call to an outside service (catalogues, shops, search, model providers, engines)
  MUST go through one wrapper: up to three retries with pauses of 0.1, 0.5 and 1 second on a network
  error or a temporary refusal, then the host is set aside for a configured time and the stage moves
  on to the next source. Set-aside hosts and the reason are shown by the stand door.

**Versions of book-level results**

- **FR-052**: Metadata and the table of contents MUST belong to the book, not to a run, and be
  versioned. A run MUST use the current versions and record which ones it used. Recollecting them
  MUST be possible on request and MUST happen when their knobs or the code of their sources
  changed; it creates new versions and never alters the old ones.
- **FR-053**: The book's result MUST be the bundle of its best finished run: highest verdict
  (`ok` over `dirty` over `bad`), ties broken by structure metrics, then by the latest run. It is
  recomputed whenever a run of the book finishes, and the catalogue record points to it.
- **FR-054**: A submission MAY consist of several PDF files in a given order (a book split into
  parts or chapters); they form one book with one page sequence across the files, one table of contents
  (bookmarks of each file placed under its position), and one bundle. The book's identity is the
  ordered list of file contents; the same files in the same order map to the same record, and
  every page keeps its file and in-file page number in artifacts and reports.
- **FR-055**: Volumes of a multi-volume work, and books of a publisher's series, MUST stay separate
  books with separate bundles, linked in the catalogue through the metadata fields `series` and
  `volume`; the catalogue MUST list the books of a series in volume order.

**Doors**

- **FR-047**: Everything the owner or an external agent does (submit a book, pick a format, watch
  stages and chapters, read reports, profiles and artifacts, edit a profile, rerun a book or a
  chapter, run an evaluation set) MUST be available through an HTTP API and through MCP tools
  over the same operations. A web interface is out of scope.

**Queue**

- **FR-048**: Work MUST go through a job queue that accepts any number of books: stages that do
  not need the GPU run in parallel across books, and the GPU runs one job at a time. Queued, running
  and finished jobs per book and per chapter are visible through the doors.

### Key Entities

- **Source book**: the submitted file or ordered files, identified by their contents, and what
  probes found in them (pages, text layer presence per page, bookmarks, printed contents, layout
  traits).
- **Catalogue record**: the stand's entry for a book: metadata fields, each with value, source and
  confidence or marked unknown; table-of-contents sources found; the table of contents if intake
  extracted it; links to the book's runs.
- **Knob registry**: all knobs grouped by question, each with options, explanation and probe.
- **Knob**: one question about a book (for example "where the table of contents comes from") with
  a value or a nested group of knobs.
- **Preset**: a named partial profile used as a starting point.
- **Book profile**: the resolved set of knob values for one book, each with source and evidence.
- **Profile candidate**: one profile the stand tried, with its measurement and keep or drop reason.
- **Chapter**: one entry of the reconciled table of contents and the unit of assembly; has its page
  range, level, knob overrides, checks, verdict and artifacts.
- **Run**: one processing of one book with one profile; owns its run directory and stage artifacts;
  can be resumed.
- **Stage artifact**: the output of one stage of a run, with stage name, inputs, profile and
  engine versions.
- **Bundle**: the deliverable of a run: document, images, profile, report.
- **Quality report**: metrics and verdict of a bundle.
- **Evaluation set**: the books used for regression, with their best known profiles.
- **Gate**: a pre-registered pass rule for an evaluation run (columns, tolerance, untouchable
  books) and its result.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For 100% of submitted books, a run ends either with a bundle and a report, whatever
  the verdict, or waiting for attention with every failed chapter and its error visible through
  the doors; no run ends silently.
- **SC-002**: On evaluation books with bookmarks, run with bookmarks switched off, at least 95% of
  bookmark chapters are found at the right level (initial target, revised after the first
  evaluation run).
- **SC-003**: On books whose verdict is `ok`, no chapter sits below its own sections and no
  heading exceeds level 6, checked across the whole evaluation set.
- **SC-004**: 100% of image links in every bundle resolve after the bundle directory is moved.
- **SC-005**: A run killed at any point and restarted redoes at most the one stage or chapter
  that was in progress, and its bundle is identical to an uninterrupted run on deterministic stages.
- **SC-006**: For every value in every resolved profile, the owner can find the measurement that
  chose it in under a minute from the bundle.
- **SC-007**: Profiles assembled by the stand reach at least 90% of the best known profile's
  structure score on each evaluation book (initial target, revised after the first evaluation
  run).
- **SC-008**: A change to shared behaviour that worsens any evaluation book is reported with the
  book named, before the change becomes a default.
- **SC-009**: Bringing the stand up on a machine with the rag-lab downloads fetches no engine
  image or model weight that is already present.
- **SC-010**: On the evaluation set, 100% of metadata fields are filled and correct for every book
  whenever the value exists in the book or in an external catalogue; a field is left unknown only
  when no source has it, and then it lists every source tried.
- **SC-011**: On scanned evaluation books, chapters are found at the right level as often as on
  text books within a margin set at the first evaluation run.

## Assumptions

- The single user is the project owner; there are no accounts, roles or sharing in this feature.
- Submitted PDFs are lawfully obtained by the owner; licensing checks are out of scope.
- Books are of any genre (technical, fiction, children's, textbooks, poetry) and any language; no
  stage assumes a language, and language-specific rules (ISBN registration groups, title-page
  patterns) are tables that grow with the books, not code paths for two languages.
- Input in this feature is PDF only; EPUB, HTML and other formats are later features.
- Output in this feature is Markdown only; the Docling format for RAG and others are later
  features.
- An agent layer inside the stand is out of scope for this feature; the doors are designed so it
  can be added later without changing them.
- Two kinds of model use are distinct. Inside the stand, steps such as reading title and contents
  pages or naming the subject call a model built into the stand, local or a cheap
  OpenAI-compatible cloud one, chosen per step by a knob. Outside the stand, an external agent
  (for example Claude Code) drives the stand through its MCP tools and designs knobs. All
  conversions, artifacts, profiles and reports stay on the stand's local storage.
- Run time per book is not bounded in this feature; long runs are acceptable as long as they
  resume.
- The findings and research carried over from rag-lab (`~/working_docs/projects/ocr-lab/notes/rag-lab-intake/`) are the starting defect
  list and the first candidates for knobs and presets.
- The first evaluation set is drawn from the rag-lab corpus books already studied there.
- Already downloaded in rag-lab and reused: the converter engine images with their models baked
  in, the shared model weights cache, local model server data, and the source books themselves.
- External book catalogues (Open Library, Google Books, publisher sites) may be queried freely
  for metadata and for the table of contents; taking these from public sources is allowed.
- "Subject" is a short free label of the book's field and kind (for example "databases,
  textbook" or "detective novel"); a fixed taxonomy is out of scope.
