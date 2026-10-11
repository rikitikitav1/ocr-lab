# What the report's numbers mean

Every run writes `report.json` and `report.md` into its bundle (`bundles/<book>/<run>/`). They hold
numbers only, with no verdict label: whether a chapter is good enough is for the reader to decide. All
numbers are read from the assembled chapter and from the book's own PDF, never from a gold. This page
says how each one is computed. The schema is in
[contracts/bundle.md](../specs/001-pdf-book-to-markdown/contracts/bundle.md); the code is
`app/quality/chapter.py` (a chapter's checks), `app/quality/book.py` (the book's totals) and
`app/job_handlers/run.py` (the bundle and `report.md`). Thresholds are in `config/quality.yaml`.

## Words

Every text comparison works on words: runs of letters, digits and underscores (`\w+`), lower-cased,
counted as a multiset. A word met three times counts three times. These shares ignore order, so a
paragraph in the wrong place costs nothing (see [Order](#order)), while a paragraph written twice costs
its words once more. The split does not suit CJK: a run of hanzi is one word, so the word measures,
agreement included, mean little there.

## Layer pages and `layer_min_words`

The **text layer** is the text the PDF itself holds for a page, read by PDFium (a word PDFium breaks
over one row is joined back first). A page of the chapter
counts as a **layer page** when its layer has at least `chapter.layer_min_words` words (20). A cover, a
full-page figure or a blank page falls below that and is left out of `lost_text` and `extra_text`
both, so a picture neither helps nor hurts them.

`layer_pages` is the count of such pages, per chapter and summed for the book. Pages read by
recognition (a scan, or pages the intake probe found without a usable layer or garbled) never count as
layer pages: there is no layer to compare with.

## The book's own furniture

Running heads and page numbers are not text. Before any comparison, the words of the book's own
furniture are taken off the layer side, read from the layer alone (`app/stages/assemble.py`,
`app/stages/running_heads.py`):

- a **running head** is a top or bottom line of a page whose text, with page numbers at its ends
  stripped, is a top or bottom line on 3 or more pages of the book. A top line on the first page where
  it appears is a chapter's opening title, not a head;
- a **folio** is a page's top or bottom line that is a bare number of 1 to 4 digits (dashes and other
  marks around it allowed) whose page minus number gives the same shift on 3 or more pages. A "5" in a
  query's output does not rise with the pages and stays text.

What an engine set aside as furniture is not subtracted. See
[lost text against the book's own heads](experiments/2026-10-10_lost-text-against-the-books-own-heads.md).

## `lost_text` and `extra_text`

Per chapter, over its layer pages:

- *want* = the layer words of those pages, minus the furniture words above;
- *got* = the words of the assembled blocks on those pages, plus the chapter's title (the writer puts
  it above the blocks);
- `lost_words` = words in *want* not matched in *got*; `extra_words` = words in *got* not matched in
  *want*;
- `lost_text` = `lost_words` / words in *want*; `extra_text` = `extra_words` / words in *got*. Shares
  are 0 to 1, rounded to three places.

When two chapters meet on one page, the assembler cuts the page at their titles, and the page is left
out of both chapters' own shares: the book scores it once, its layer against the words every chapter
wrote on it. The cut is counted in the passes (`shared_cut_blocks`, `shared_cut_start`, `shared_cut_end`,
and `shared_title_missing` when a title is not found on the page).

A chapter with no layer pages has `lost_text` and `extra_text` of null (`n/a` in `report.md`).

For the book, words are summed over the finished chapters before dividing: `lost_text` = all lost words
/ all layer words, `extra_text` = all extra words / all words written on layer pages. A long chapter
weighs more than a short one. Failed chapters are left out.

`report.md` shows them as "text lost against the layer ... on N pages" and "text not in the layer".

## `set_aside_words`

The lost words that some engine had set aside as furniture (a running head, a footer, a page number),
beyond the book's own heads and folios. It is a part of `lost_words`, not an addition to it: it says how
much of the lost text an engine dropped on purpose. A caption or a section line an engine wrongly took
for a footer shows up here. `report.md`: "layer words an engine set aside beyond the book's heads".

## `layerless_words`

Words written into the chapter from pages that are not layer pages: pages whose layer has fewer than 20
words, and every recognised page. `extra_text` cannot see these words, so a cover whose thumbnails were
read into text would otherwise pass unnoticed. On a fully scanned book every word is layerless.
`report.md`: "words from pages the layer check does not see".

## Recognised pages and the engines' agreement

A page without a usable layer is read by both engines in OCR mode. With no layer to compare with, the
measure is how far the two readings agree: word F1 between the preferred engine's words and the other
engine's words on that page.

- `recognised_pages`: recognised pages that got an agreement value.
- `agreement`: per chapter, the mean over its recognised pages; `agreement_min`, the lowest page. For
  the book, the mean weighted by each chapter's recognised pages. Null when there are none.
- `picture_pages`: recognised pages where **both** engines read fewer than `layer_min_words` words (a
  plate, a full-page picture). They get no agreement value, since a caption against nothing is no
  measure of recognition. One engine failing alone stays an agreement of 0 and stays visible. The book's
  figure is the sum of each chapter's `pages_picture` pass count.

- `dictionary_share`: on recognised pages, the share of the bundle's words of two or more letters that a word list
  of the book's languages knows (`wordfreq`); `dictionary_words` is how many were counted. It needs no gold and no
  second engine: it falls where recognition writes words that do not exist ("уменышаться", "asezarilor" for
  "aşezărilor"). Names, terms and short junk that happens to be a word keep it below 1, so it is read between books
  of one language. Null for a book with a language written without spaces (Chinese, Japanese, Korean, Thai), whose
  words the list cannot split, and for a book with a language `wordfreq` has no list for (Latin), whose words would
  count as unknown. For the book, the mean weighted by the words counted. On the shelf's Russian scans it
  reads 0.95 to 0.99 (book 9 0.988, where agreement is 0.385 because Docling returned empty pages).

`report.md` lists the chapters with the least agreement. See
[picture pages on recognised ranges](experiments/2026-10-10_picture-pages-on-recognised-ranges.md).

## Sections: `subs` and `subs_found`

`subs` are the toc's sub-entries of a chapter (the sections the table of contents lists under it).
A sub-entry is **found** when some heading of the assembled chapter matches its title, whitespace
collapsed and lower-cased, at a similarity of 90 or more (rapidfuzz `WRatio`). `subs_missing` lists up
to ten titles not found. The book sums both, and `report.md` shows "toc sub-entries found as headings"
and the chapters with the most missing.

## Headings

- `headings`: heading blocks in the assembled chapter.
- `long_headings`: headings longer than `chapter.heading_max_words` (20) words, which are paragraphs an
  engine took for a heading.
- `empty_headings`: headings with no text.
- `max_heading_level`: the deepest Markdown level the chapter is written at, read from the chapter's written
  Markdown (code fences skipped); `title_level` is the level of the chapter's own title. The book reports the deepest
  of its chapters and names the deepest of those whose headings go more than two levels below their title, past
  their sections and sub-sections, which most books have.
- `headings_not_below_title`: headings written at or above the chapter's own heading, read the same way. The writer
  is meant to put every heading below its chapter, so this checks the output, not the rule; a chapter where it is
  not 0 is named in the book's `chapters_below_sections`.
- `running_heads_in_text`: paragraphs that are the book's own running heads or bare page numbers (compared the way
  the running heads are found, a page number at either end ignored). Headings are left out, since a section title is
  often its page's running head too.

## Duplicates

A paragraph met in two or more chapters is text that two chapters' page ranges took twice. Each
chapter's Markdown is split into paragraphs at blank lines, fenced code is removed first (a listing
repeated on purpose is not a page taken twice), whitespace is collapsed, and paragraphs shorter than
`book.duplicate_min_chars` (120 characters) or starting with an HTML comment are skipped. `duplicates`
in `numbers` is the count of such paragraphs; the top-level `duplicates` list gives each one's chapters
and its first 80 characters.

## Repeated paragraphs

`repeated_paragraphs` counts paragraphs of `chapter.repeated_min_chars` (120) characters or more met
again inside one chapter, whitespace collapsed: text an engine or a merge wrote twice. The book sums it.
It differs from `duplicates`, which is one paragraph in two chapters.

## Order

`out_of_order` is the share of a chapter's layer word runs that moved. A run of `chapter.order_run_words`
(6) words met once in the layer and once in the chapter is an anchor (`order_anchors`). The anchors are
taken in layer order; those off the longest run that rises in the chapter are out of order
(`out_of_order_anchors`), and `out_of_order` is their share, null with no anchors. The book divides the
summed counts. A swapped paragraph and a footnote set before its text both show here.

## Images and links

- `figures`: figure blocks over all chapters; per chapter, `figures_not_kept` counts figures whose image
  is not a file yet (written as a comment, not a broken link).
- `files`: image files written with the chapters' current text.
- `links`: image links (`![...](images/...)`) in the document.
- `broken_links`: distinct linked names with no file behind them.
- `unreferenced_files`: files no link points to.

## Pages cut

`pages_cut` names the pages the bundle leaves out, by reason: `contents`, the printed contents pages the
toc found (the toc is built another way), and `cover`, page 1 when the first real toc entry starts after
it (metadata reads the cover instead). Per chapter, the `pages_cut` pass count says how many of its pages
were cut.

## Service chapters

Each chapter carries a `role`: `service` for the unnumbered chapters before the first numbered one (a
preface, an introduction) and after the last (a conclusion, a bibliography, an index), `body` for the
rest. A letter counts as a number ("Appendix A"). Nothing is marked when numbering starts after the
first 15% of the book's pages, and nothing after the last numbered chapter when more than 15% of the
pages follow it. Service chapters stay in the document, with `role=service` in the comment that opens
each chapter, so a later reader can drop them. `report.md` lists them with their toc sub-entry counts.
See [service chapters on both edges](experiments/2026-10-10_service-chapters-on-both-edges.md).

## Worst chapters

`worst` lists, for each of `lost_text`, `extra_text`, `out_of_order`, `agreement` and missing sub-entries, the
`book.worst_chapters` (5) worst finished chapters: highest lost, extra and out of order (chapters at 0 are
not listed), lowest agreement, most sub-entries missing.

## Passes

`checks.passes` in each chapter counts what the assembler did: for example `paragraphs_to_code`,
`code_rebuilt`, `pages_recognised`, `pages_picture`, `pages_cut`, `title_dropped`, and
`shared_cut_blocks`, and `furniture_<engine>`, the furniture blocks each engine set aside. These are counts of actions, not
quality numbers; they show which passes fired on a chapter.

## Versions

- `run.made_by` groups the chapters by the code version, engine builds and languages that made them. More than
  one group means chapter reruns mixed versions in one bundle.
- `profile` names the profile the run was made with: `knobs_applied` lists run knobs whose value differs
  from the registry's default, `chapter_overrides` a chapter's own values from a rerun.

## Which run is the book's result

A book may have several finished runs. Its result is the best finished run on the book's **current**
toc version (a run on an older toc cannot be the result: the chapters come from the toc). Runs are
ranked by `app/stages/result_run.py`, recomputed whenever a run finishes and cleared when a new toc
version is made, in this order:

1. least `lost_text` (a run with none counts as 1.0);
2. the largest share of toc sub-entries found (`subs_found / subs`, 1.0 when there are no sub-entries);
3. fewest duplicate paragraphs;
4. least `extra_text` (none counts as 1.0);
5. on a full tie, the newest run.

## Limits

- `lost_text` and `extra_text` ignore order: a paragraph in the wrong place, a table read row by column,
  or two columns interleaved cost nothing in them as long as the words are there. `out_of_order` sees
  runs that moved, but only those met once, so short or repeated text escapes it.
- Structure inside a page (code lines, table cells, heading levels) is not in these numbers; it is
  measured against a gold by the element evaluation, not at run time.
- Agreement says two engines read the same words; both can be wrong the same way, and it does not tell an
  empty engine from a disagreeing one.
