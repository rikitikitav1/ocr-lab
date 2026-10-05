# ocr-lab Constitution

## Core Principles

### I. Autonomous Conversion

The user hands over a book, picks an output format, and gets back a finished bundle. No human step
sits between the two.

- One command (or one job) takes a source file and a target format and produces the full output
  bundle described in Output Contract.
- The agent, not the user, assembles the book's profile (Principle II), runs the conversion and
  judges the result.
- When the agent cannot reach acceptable quality, it still produces the bundle and says so in the
  verdict, naming the defects and the knobs it tried. Poor quality never stops a run.
- A failure is different from poor quality: when a step still crashes after its retries, the run
  finishes what it can, then waits for attention, visible through the doors with the error, until
  an agent or the owner has looked into it and restarted the failed part. It never fails silently.

### II. Book Profile of Knobs

Every book is processed by its own profile: a nested tree of knobs, each answering one question
about this book.

- Knobs are grouped by question, for example: where the table of contents comes from; how a
  chapter title, a section heading, a code block, a note or sidebar, a table, a caption, a running
  head is recognised; how images are cut and named. Each group holds knobs, and a knob holds a
  value or a nested group.
- Every knob is declared in one registry with its options, a one-line explanation, and the probe
  or metric that tells whether its value fits a given book.
- Presets are named partial profiles (for example "O'Reilly PDF", "scanned Russian textbook",
  "HTML site dump") that seed a profile. A book's profile MAY override any knob of its preset, and
  the profile of a book MAY change between runs.
- No genre is assumed: a technical manual, a children's primer and a detective novel go through
  the same stand. Anything genre-specific lives in knobs and presets, never in shared behaviour.
- The agent's first job is to assemble the profile: probe the book, pick a preset, try candidate
  values for the knobs that matter, measure, and keep the best. Each chosen value records its
  evidence (the probe or measurement that chose it).
- The agent's second job is to grow the registry: when no existing knob or option fixes a defect,
  the agent designs a new knob or option, implements it, and measures it on the books that showed
  the defect. Growing the registry is part of the product, not a side task.
- The profile is data, stored with the book and in the bundle, so a run can be repeated and a
  profile can be read and edited by a human when needed.

### III. Measured Quality (NON-NEGOTIABLE)

No output ships without a measurement. Every conversion writes a machine-readable quality report
next to the document.

- The report MUST cover at least: structure against the book's table of contents (chapters found,
  levels, order), text fidelity against the source text layer, heading level sanity (no level past
  the format's maximum, no chapter below its own sections), image and link integrity, and an
  overall verdict (`ok`, `dirty`, `bad`) with the reasons.
- Metrics MUST measure structure, not only words. Word similarity on short page cuts stays high
  while heading levels are wrong, so it is never the sole gate.
- A verdict of `ok` with lost structure is a defect of the metric and is fixed as such.
- The same metrics drive knob selection (Principle II), so the agent optimises what the report
  shows and not a private score.
- Gold references are preferred where they come free: books with PDF bookmarks serve as gold for
  the other table-of-contents sources, which are run with bookmarks switched off.

### IV. Structure Matches the Book

The sections of the output match the sections of the book: same chapters, same nesting, same order.

- The table of contents is acquired first and from several sources, then reconciled: PDF
  bookmarks, the printed contents pages, numbering in the text, typography, and a model reading
  the contents pages as the last source. Which sources are used and in what order is a knob group.
- Each heading carries the source that decided its level, and the report counts headings per
  source.
- Heading levels are decided across the whole book, never per processing chunk. Chunking, when an
  engine needs it, follows chapter boundaries.
- Running heads, footers, sidebars and captions MUST NOT become headings. Duplicate pages are
  removed and reported.

### V. Format-Agnostic Core

Inputs and outputs are adapters around one internal document model.

- Readers turn a source format into the internal model. PDF comes first; EPUB, HTML and other
  e-book formats are added as further readers.
- Writers turn the internal model into an output format. Structured Markdown comes first;
  DoclingDocument (for RAG) and other structured formats are added as further writers.
- Conversion engines (Docling, MinerU and others) sit behind adapters with pinned versions and do
  not leak their quirks past the internal model. The engine for a book or a page range is a knob.
- Adding a reader, writer or engine MUST NOT change the output of the existing ones; the regression
  run proves it.

### VI. Gated Shared Behaviour

A book's own profile changes freely, measured on that book. What is shared by many books changes
only through gates.

- Shared means: the code behind a knob option, a preset, the registry's fallback values, and the
  metrics. A change there touches every book that uses it.
- Before changing shared behaviour, run the evaluation set as it is, collect every defect into one
  list, classify by how many books show it and by mechanism, then plan. Defects are not fixed one
  by one in the order they turn up.
- Each change is probed and measured on its own, before and after, naming which books moved.
- A fix seen on one or two books enters as a new knob or option set in those books' profiles, not
  as a change to shared behaviour.
- A preset or a shared option changes only after a full evaluation run with a gate registered
  before the run (columns, tolerance, books the change must not touch). On deterministic stages
  "no harm" is a list of every book that got worse, with a reason, not a noise band.
- The same option chosen on several books for the same reason is a candidate for a preset and goes
  through the gate then.
- A new knob or option MUST NOT change the output of books whose profiles do not select it; the
  regression run counts books that changed without selecting it.

### VII. Reproducible Runs

The same source, profile and engine versions produce the same bundle byte for byte on
deterministic stages.

- The resolved profile (preset plus overrides), engine versions and table-of-contents sources used
  are stamped in the bundle.
- Stochastic stages (model calls) record model id and parameters, and their output is cached so a
  rerun reproduces it.
- Measurements that back a decision are stored as files a reader can open later.

### VIII. Artifacts and Resumable Runs

Every stage of every run leaves a file behind, so any result can be traced back step by step, and
an interrupted run resumes from the last saved point.

- Each stage writes its output as an artifact: probe results, the table of contents from each
  source and the reconciled one, raw engine output per chunk, the internal model before and after
  each rule, the writer's output, the metrics.
- The agent's profile search is kept too: every candidate profile it tried, its measurement, and
  why it was kept or dropped. The same holds for knobs it designed and their trial runs.
- Each artifact names its stage, its inputs, the resolved profile and the engine versions.
- Runs are append-only: a new run writes a new run directory and never overwrites an earlier one.
  The bundle names the run that produced it.
- Artifacts are removed only by an explicit cleanup command, never as a side effect of a run.
- Stage artifacts are the checkpoints. A stage counts as done only when its artifact is written
  completely (written aside, then moved into place), so a crash never leaves a half-written one.
- A run interrupted at any point (crash, kill, reboot, engine timeout) resumes in its own run
  directory from the last completed stage or chunk, without redoing finished work and without
  manual cleanup. This covers the agent's profile search as well.
- A finished stage is reused on resume only if its inputs, profile and engine versions are
  unchanged; otherwise it and everything after it are redone.
- A resumed run produces the same bundle as an uninterrupted one; a test kills runs mid-stage and
  checks this.

## Technical Constraints

- Python is the default language; a plan that picks another one justifies it.
- The stand runs under Docker Compose: one `docker compose up` brings up the pipeline, the engines
  and their dependencies.
- Cloud models MAY be used for agent work (profile search, knob design, reading contents pages).
  Their inputs and outputs are cached as artifacts (Principles VII and VIII).
- Every call to a service outside the stand goes through one door that retries it with short pauses
  and then sets the host aside for a while, so one flaky site never stalls a stage and the next
  source is tried; the set-aside hosts are visible through the stand's doors.
- All conversions, artifacts, profiles and reports are stored on our side, on the local
  filesystem (a mounted volume). Object storage such as S3 may come later and is not designed for
  now.

## Output Contract

Every conversion produces one bundle directory:

- the document in the chosen format (for Markdown: `<book>.md`);
- an `images/` folder with every extracted figure, each referenced from the document by a relative
  link that resolves inside the bundle;
- the resolved profile (`profile.yaml`), with the evidence for each chosen knob value;
- the quality report (`report.json`, plus a short human-readable summary).

Rules for the bundle:

- Every image link in the document resolves to a file in `images/`, and every file in `images/` is
  referenced at least once. The report counts both.
- Markdown headings use levels 1 to 6 only; the book title is level 1, chapters level 2 unless the
  book has parts.
- Code blocks, tables and lists keep their type; code is taken from the text layer where one exists.
- The bundle is self-contained: moving the directory MUST NOT break links.
- The bundle is the deliverable; the stage artifacts of its run (Principle VIII) live in the run
  directory, and the report names it.

## Development Workflow

- An evaluation set of books (with and without bookmarks, with and without printed contents,
  single-column and multi-column, technical, fiction, children's and image-heavy books) is the
  regression suite. Changes to shared
  behaviour run against it before merge, and the result file is kept.
- The evaluation set also measures the agent itself: how close its assembled profiles come to the
  best known profile per book, and how often it had to grow the registry.
- Every principle above that names a check is enforced by an automated test or a report field,
  not by review alone.
- Code comments state what the code does and why in one plain line; they never reference commits,
  plan sections, review rounds or dates.
- Plans, research notes and logs live outside the repository, in `~/working_docs/projects/ocr-lab/`.
- Findings carried over from rag-lab (`~/working_docs/projects/ocr-lab/notes/rag-lab-intake/`) are the
  starting defect list and the first candidates for knobs, not settled design.

## Governance

This constitution overrides other project practices. Where a plan or a change conflicts with it,
the constitution wins until it is amended.

- Amendments are made by the project owner, recorded in this file with an updated version and
  date, and any plan or template that depends on a changed principle is reviewed in the same
  change.
- Versioning follows semantic versioning: MAJOR for removing or redefining a principle, MINOR for
  a new principle or materially expanded guidance, PATCH for wording and clarifications.
- Every `/speckit-plan` run checks the plan against each principle in its Constitution Check;
  a violation is either fixed or justified in the plan's complexity tracking.
- Reviews verify that a change ships with its measurement (Principle III) and, for shared
  behaviour, its gate run (Principle VI).

**Version**: 1.1.0 | **Ratified**: 2026-10-05 | **Last Amended**: 2026-10-05
