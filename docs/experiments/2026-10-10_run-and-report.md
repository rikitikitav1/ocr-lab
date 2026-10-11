# 2026-10-10 - The run and its report

Lead: after the toc and the assembler, the run produces a bundle and a report that say how much of the
book arrived and which settings made it. The report must not call furniture lost text, must not punish a
picture plate as a recognition failure, and a refactor of how settings reach the passes must change no
output. The measurements ask, change by change, which numbers move and on which book.

## Setup

- **Reference pair**: book 38 (PostgreSQL Notes for Professionals, 74 pages) and book 111 (Romanian,
  1905); runs 16 and 17 on the old code, 22 and 23 on the new, then 24 and 25, 26 and 27, 28 and 29. The
  gate set is the reference pair, not the shelf.
- **Scan verdict**: checked over the whole shelf.
- Gates were written before each run; byte identity is checked with `cmp` and `diff -rq` on the bundles.
  What every report number means is in [measurement.md](measurement.md).

## How the numbers moved

| step | numbers after | got worse |
|---|---|---|
| old rule (runs 16, 17) | 38 lost 0.002, extra 0.010; 111 lost 0.044, extra 0.040 | baseline |
| own heads and folios (22, 23) | 38 lost 0.003, extra 0.007, set-aside 13; 111 lost 0.044, extra 0.041, set-aside 8 | 38/3 +7 lost words (running head read as opening title) |
| picture pages (24, 25) | 111 chapter 4 agreement 0.0 → none; 38 nothing; no scan verdict flips | none |
| both engines under 20 words (28, 29) | documents identical; 38 `layerless_words` 178, 111 picture pages 1 and `layerless_words` 4 | none |
| knobs and profiles (26, 27) | 38 and 111 byte-identical on the default profile | none |

## Changes

The table above carries the numbers; the subsections keep what a row cannot say: mechanisms, losers, reverts.

### Lost text against the book's own running heads and folios

`lost_text` is the share of the layer's words missing from an assembled chapter. The old rule subtracted
every word any engine set aside as furniture, so a block an engine wrongly set aside (a caption, a
footnote, a real section line) could never count as lost. Change (`app/quality/chapter.py`,
`app/stages/assemble.py`): subtract only the layer's own running heads (top or bottom lines repeated on 3
or more pages, except a top line on the first page it appears, read as a chapter's opening title) plus
bare folios on a page's top or bottom line; report the layer words an engine set aside beyond those and
missing from the chapter as `set_aside_words`. Gate: `lost_text` may rise only by folios the old rule took
from the engines and heads the layer rule misses; every chapter whose lost words move is listed;
`set_aside_words` per chapter; no other check may move.

| book | lost_text | extra_text | set_aside_words |
|---|---|---|---|
| 38 | 0.002 → 0.003 | 0.010 → 0.007 | 13 |
| 111 | 0.044 → 0.044 | 0.040 → 0.041 | 8 |

Sub-entries found and agreement did not move on either book. Chapters whose lost words moved: 38/3
"About" +7 (the running head on page 5 appears there for the first time, so the layer rule takes it for a
chapter's opening title; the engines were right; a known edge, not fixed); 38/117 +6 ("Timestamp
difference between two dates yearwise", a real section line an engine set aside: the case the change was
made for); 111/4, 19, 27, 28 -1, -1, -1, +1 (folios printed between long dashes, 17 with a dash on each
side, now subtracted as the book's own). On those four, set-aside counts of 5, 2, 0 and 1 are garbled
folios the rising rule cannot read (68 with stray dashes and a bullet around it passes, "') Un
formulai'" does not).

`extra_text` moved too, against the gate's "no other check may move": down on 8 chapters of 38 (the old
rule took head words that also stand in the body off the layer) and up by 13 words on 111 (folios the
engines kept in the text now count as extra, which they are). Both are the subtraction working on the
other side of the same comparison.

Two tries before: a bare-number edge line as a folio took "5", a query's output on page 19 of book 38,
for a folio (fixed by requiring the page minus the number to repeat on 3 or more pages); bare digits
alone missed 111's folios between long dashes (dashes and other marks around the number are allowed).
Decision: default.

### Picture pages on recognised ranges

A plate in a scanned or partly scanned book gives an agreement of 0 or near it, which says nothing about
recognition, and could count twice toward the scan verdict (no layer and garbled). Change
(`app/assembly/passes.py`, `app/stages/assemble.py`): a recognised page where the preferred engine reads
fewer than `layer_min_words` (20) words is a picture page (`pages_picture` in the chapter's passes) and
has no agreement value; the scan verdict counts the union of pages without a layer and garbled pages, so
a page is counted once. Gate: no scan verdict flips over the shelf; on 111 only page 22 leaves the
agreement; nothing else moves on 38 and 111.

Scan verdict over the shelf: none flips (11 books have 1 or 2 pages in both lists; book 9 has 253 and
stays a scan). Runs 23 → 24 on 111: chapter 4 recognised pages 1 → 0, agreement 0.0 → none,
`pages_picture` 1, the "least agreement" list empty, lost, extra and set-aside unmoved. Runs 22 → 25 on
38: nothing. Book 38's one recognised page (74, "You may also like", a service chapter) keeps agreement
0.0: MinerU reads its 20 or more words of blurb, Docling nothing; a real disagreement, left as it is.

Correction, measured 2026-10-10: a recognised page is a picture page only when **both** engines read fewer
than `layer_min_words`, so one engine failing alone stays an agreement of 0 and stays visible. Also
added `layerless_words` (words written from pages the layer check does not see) and picture pages in
`report.md`'s table. Gate: the documents of 38 and 111 identical to runs 25 and 24. Runs 28 and 29:
documents identical; lost, extra, recognised pages and agreement unmoved. Book 38: `layerless_words` 178,
all in chapter 125 (page 74); book 111: picture pages 1, `layerless_words` 4 (page 22's caption).
Decision: default in the narrowed form.

### Knobs and profiles: the default profile leaves bundles byte-identical

Each assembler pass had been a value in `config/assembly.yaml`, read the same way for every book; fixes
seen on one or two books need to go in as knobs of those books. A refactor of how values reach the
passes, so the question is narrow: on the default profile does any bundle change by a byte, and does a
knob set through a profile take effect? Runs 26 and 27 against 25 and 24.

Built: `config/knobs.yaml` (run knobs in two groups, tables and code, each with options, help, a probe
and a cost; defaults stay in `config/assembly.yaml` and a test keeps the two in step; book knobs are a
third group); presets in `config/presets/` (`default`, no values of its own); `app/profiles.py` (a
profile is every run knob's value with its source and evidence, named by its sha256, one row per distinct
value set per book; `derive` makes a new one with `set` and per-chapter `chapters` overrides). A run
without a profile gets the default preset's; a rerun with overrides derives a profile and makes it the
run's. Doors: `GET /v1/knobs`, `/v1/presets`, `/v1/profiles/{id}`, `POST /v1/profiles/{id}/derive`, and
the MCP tools `knobs`, `presets`, `profile`, `derive_profile`. The bundle gains `profile.yaml` and
`report.json` a `profile` block with `knobs_applied` and `chapter_overrides`.

Gate, written before the run: on the default profile the document and images of 38 and 111 are
byte-identical to runs 25 and 24. Result: 38 (26 against 25) identical, 111 (27 against 24) identical. A
knob takes effect: run 26, chapter 4 rerun with `assembly.mono_paragraphs: false`: paragraphs turned into
code 3 → none, code blocks rebuilt from the layer 10 → 7, and the report names profile 3 (parent 1).
Decision: built and kept. Later `knobs_applied` was narrowed to list only the values that differ from
the registry's default, a preset's own values included.

## Where it stands

- Reference pair: book 38 lost_text 0.003, extra_text 0.007, set_aside_words 13, `layerless_words` 178;
  book 111 lost_text 0.044, extra_text 0.041, set_aside_words 8, picture pages 1, `layerless_words` 4.
- The default profile leaves both bundles byte-identical; no scan verdict flips over the shelf.
- Open: profile search (probes, candidates, choosing values by measuring) is not built, `search=true` says
  so.

## Caveats

- A running head on the first page it appears is read as a chapter opening (38/3). Garbled folios that do
  not read as a number stay in the layer and count as lost when the engines drop them.
- Two books, one page firing the picture-page rule on each: the reference pair, not the shelf. The
  threshold is the same `layer_min_words` that decides which layer pages count for lost text and was not
  tuned for recognised pages. A hand count of book 38's layerless words found 181 including the title;
  the report counts 178.
- Not knobs: the rules that keep running heads, sidebars, captions and chapter labels out of headings are
  not switchable in code; they hold for every book.
- Byte identity on two books shows the refactor changed no default path; it says nothing about how good
  any knob value is.
