# Experiments log

A lab journal of the changes that decide how a PDF book becomes Markdown: question, setup, result,
decision. Every rule that reads a table, a code block, a table of contents or a title page was tried
on a set of books before it was kept, and the entries below record what each try moved and on which
book. What every number in a bundle's report means is in [measurement.md](measurement.md).


Books are named by their id on the stand; [books.md](books.md) lists them.

## Methodology

- **Books are a series whose members differ a lot.** A rule that helps one book often hurts another,
  so no change is judged by an average. Each change goes through the same steps:
  0. run the whole series, or a declared sample, on the current defaults; list every defect with the
     books and places it shows on; group the defects by how many books share them and by mechanism;
     write the fix plan before fixing anything;
  1. try each change on a small probe and measure it alone: before and after, which books moved,
     which way. Several changes in one run are allowed only when each book that got worse can be
     pinned on one of them;
  2. a fix seen on one or two books becomes a knob of those books, off for the rest (a book knob, or
     a per-chapter override of a run knob);
  3. a default changes only after a gate run declared beforehand: the columns, the tolerance, and
     the books the rule must not touch. Every stage measured here repeats byte for byte, so "no harm"
     is a list of every book (or section) that got worse, each with its reason, not a noise band.
     "Nothing else moved" is counted too: books where the rule did not fire but the output changed.

  A knob set on two or three books for one reason is a candidate for the default and goes through
  step 3.
- **A column the rule writes cannot judge it.** A rule that marks chapters as service cannot be
  judged by a count of service chapters, and a rule that sets heading levels cannot be judged on cuts
  that have no outline. Each gate names a column the rule does not produce, and checks that its set
  can fire the rule at all.
- **No gold at run time.** The assembler chooses an engine, a table grid or a code reading only from
  the book itself: agreement of an engine's words with the PDF's text layer inside the same box,
  agreement of the two engines with each other, glyph advances, lines repeated at page edges. Gold
  sets only check those choices from outside.
- **Gate sets used here:**
  - *Elements* (code, tables, headings, prose): the text-PDF sections of rag-lab's `converter_gold`,
    each a cut PDF with a hand-made Markdown gold, scored per element by
    `POST /v1/eval/elements` (`app/evaluation/element_run.py`). After two gold guards, 91 sections.
  - *Table of contents*: the shelf of books that have bookmarks, collected with the bookmarks
    switched off and scored against them (`POST /v1/eval/toc` with `bookmarks_off`): the bookmarks
    are the gold. A second, outside set is HiPS, 49 open English law books with tables of contents
    written by people (`"set": "hips"`).
  - *Metadata*: `eval/gold/metadata.yaml`, fields checked by hand on the book's own pages; plus every
    changed field over the whole shelf, listed and read.
  - *Refactors and new doors that must not change output*: the bundles of reference books (38,
    PostgreSQL Notes for Professionals, and 111, a Romanian book of 1905), required to be
    byte-identical to the run before.
- **Where the numbers live**: each entry names its job ids or run ids; the per-section rows of an
  element evaluation are kept by the stand under `data/eval/` (a volume, not in git), so an entry
  carries its own table.

## How an entry is written

There is one entry per stage, at most five in all, and each is about 300 lines at most. Entries are read
months later, by someone checking whether a number still holds, so every entry uses the same sections in
the same order:

```
# YYYY-MM-DD - Title

Lead: what the stage must do, and the question the measurements answer.

## Setup               the gate set: which books or sets, what is pinned, how gates were declared
## How the numbers moved   one table: baseline, then one row per change with the numbers after it
                       and the members that got worse
## Changes             one ### subsection per change, in the order made; only what the table cannot
                       say: mechanism, a loser, a revert, the decision (default / knob / reverted)
## Where it stands     the stage's current numbers and what is open
## Caveats             known edges, merged and deduplicated
```

`Setup` names where the numbers come from, so a reader who scrolls straight to a table finds the
coordinates directly above it, for example:

```
**Set** `converter_gold` text-PDF sections (n=91) · **engines** Docling, MinerU · **jobs** 1165 against 1163
```

Each entry also follows these rules:

- **One entry per stage.** A new change of a stage is a new subsection and a new table row in that
  stage's entry, not a new file.
- **Every number carries its n and its set**, written beside the table it belongs to rather than
  once for the whole entry. A count of chapters found on the bookmarks-off shelf and a count on HiPS
  are not two measurements of one thing.
- **Every comparison names who moved.** The stages here are deterministic, so a delta is not read
  against an interval: it is read as the list of books or sections that got better and worse, with
  the reason for each loser. Where a stage calls a model, the entry says so.
- **For anything shaped as a gate, the rule is written before the run**, and the entry says so. If a
  criterion was chosen after the numbers were seen, the entry says that too.
- **Corrections are appended, not rewritten.** When a later run overturns an earlier number, the change
  it corrects gets a `Correction, measured on YYYY-MM-DD` paragraph naming the run that did the
  correcting. The original text stays as written.
- **Link files, not lines.** Write `app/assembly/passes.py`, not `passes.py:288`. Line numbers go
  stale within a week.
- **Record results, not opinions about the method.** The entry states what was measured and what it
  cost, and leaves the judgement of the approach to the reader.

---

## Entries

| date | experiment | what it covers |
|---|---|---|
| 2026-10-10 | [The table of contents](experiments/2026-10-10_toc.md) | Sources reconciled, HiPS as an outside gold, recognised contents, the bookmarks-off baseline and changes A to E, service chapters, Farsi book knobs, Roman numerals |
| 2026-10-10 | [Assembling a chapter's elements](experiments/2026-10-10_elements.md) | Both engines on defaults, the page referee, code from the text layer, tables by agreement with the layer |
| 2026-10-10 | [Metadata](experiments/2026-10-10_metadata.md) | Title pages without word lists, a layer in a shifted encoding, an edition equal to the volume |
| 2026-10-10 | [The run and its report](experiments/2026-10-10_run-and-report.md) | Lost text against the book's own heads, picture pages on recognised ranges, knobs and profiles byte-identical |
| 2026-10-11 | [A raw run of the shelf](experiments/2026-10-11_raw-run.md) | 40 books on the defaults, defects by mechanism, the layer reader, shared pages, GPU memory, the open defects |
