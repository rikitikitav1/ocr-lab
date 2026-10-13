# 2026-10-12 - A book's structure from its headings, read as pictures

Lead: a book with no bookmarks and no contents placed on its pages fails as "structure not recognised" once it is
over 100 pages (book 55, a 510-page scanned UNIX manual). The question: can the headings of the whole book, read
page by page, give its chapters well enough to be the last try before that failure, for scans and text books alike.

## Outcome

The method works where it is used, as the last try before a book fails, and it is in the code on by default (the
book knob `toc.from_headings` turns it off). On the 20 development books read as pictures, with every change below,
it finds 310 of 331 counted chapters (94%); 45 of them sit below the top level and 53 extra lines stand as chapters
over all 20 books. On the four text books of the third gate, never looked at before, it finds 39 of 46 (85%), where
the stage itself with bookmarks off finds 41 of 46 through their printed contents; on 21, where the stage finds none,
it finds all 8. The gates below failed against bars set for a shared default on books that have a contents (extra at
most 10% of the chapters on every book), and those misses are one or two extra lines a book, or an edited volume
whose articles' sections take the chapter level. Not served: chapter titles set as pictures (8, 9), and a reference
manual whose every subhead looks alike (55), which the guard of half a chapter a page turns into an honest failure.

## Setup

- **Input**: every page read by MinerU as a picture, the way a scan is read (`read_range` with
  `force_raster_only`), so text books with bookmarks stand in for scans with a known answer. A block gives its type
  (`doc_title`, `paragraph_title`, `text`, furniture), its box and its text; the type size is taken as the square
  root of the box area per character. That proxy moves with the length of the text: on 114, where every chapter
  title is 28.8 pt in the text layer, it gives 45.4 for "ПРЕДИ" and 38.8 for "ГЛАВА 11". The kept reading has no
  lines, so no size free of length is at hand.
- **Gold**: the book's bookmarks after its knobs; no method reads them or the text layer. Scored with the toc
  scorer as the bookmarks-off measurement calls it (title match, page within 1, chapters before the printed
  contents not counted, service chapters counted apart). The first gate and the first step-0 table used the bare
  scorer; step 0 is rescored below.
- **Prior art read first**: Marker (height clusters, a line repeated on 20% of pages or 3 in a row dropped),
  docling-hierarchical-pdf (numbering, then size clusters with bold breaking ties, a line repeated at one height
  dropped), PaddleX (a vote of numbering, style order and height cluster), MinerU (a model levels the titles),
  pdf.tocgen (hand recipes). None uses a change of running head as a chapter mark; the owner left it out, since only
  some books carry the chapter there.
- **Methods**, each scored alone, then an arbitration across them:
  - A. size clusters over the set-apart blocks;
  - B. the PaddleX vote;
  - C. MinerU's own types and levels;
  - D. a local model over the list of titles with page and size;
  - E. (owner) headings grouped by style, a group of at least `min_chapters` (5) spread over the book is the
    chapters, a running number is strong evidence, smaller larger-set groups join as siblings; a model only when
    the rules leave it open;
  - ARB. a chapter start most methods hold, at any level.

  D was never run (it needs the card free of MinerU). B and ARB were dropped after step 0: a vote over correlated
  methods on one candidate list adds no evidence, and neither was better anywhere.
- **Where it sits**: after every source today, before one chapter (at most 100 pages) and before "structure not
  recognised", which it reaches itself when no chapter level is found.
- **Book sets**: development 7, 113, 1; first gate 114, 115, 73; step 0 over 17, 8, 54, 22, 41, 80, 68, 109 and the
  six above; a second gate on books not looked at.

## First gate: failed

Development set first, with four fixes made while looking at its numbers (digits kept in the repeat key, the chapter
level spread over 40% of the book, only text and title blocks as candidates, dialogue lines left out). Then the
probe was frozen and run on 114, 115, 73. The bar: on each book, chapters found >= 90% of gold chapters and extra
chapters <= 10% of them.

| book | method | chapters found | of them below the top | extra (bar) |
|---|---|---|---|---|
| 114 | A / C / ARB | 24/25 | 22 / 5 / 22 | 2 / 2 / 2 (2) |
| 115 | A / C / ARB | 19/21 | 0 / 0 / 0 | 29 / 16 / 28 (2) |
| 73 | A / C / ARB | 2/8 | 1 / 0 / 0 | 3 / 5 / 3 (0) |

B was the worst on every book. Mechanisms: the prologue and epilogue lines took the chapter level, because the
size proxy reads their short titles as larger, not because the book sets them larger; small-caps first lines of chapters and the credits counted as headings; OCR
in titles ("ГЛАВА II" for 11) made a right page count as missed and extra; on 73 the parts are set no larger than
the sections. 113-115 are one trilogy in one layout and 113 was in the development set, so the gate was neither
independent nor varied; a wider step 0 follows.

## Step 0

The probe frozen with E added, over 14 books: the six above and 17, 8, 54, 22, 41, 80, 68, 109 (several
publishers, Russian and English, fiction, law, programming). Found / below the top / extra chapters, scored as the
run scores:

| book | counted chapters | A | C | E |
|---|---|---|---|---|
| 7 | 10 | 10/0/1 | 10/0/3 | 10/0/4 |
| 113 | 24 | 24/0/8 | 24/4/3 | 24/2/0 |
| 1 | 20 | 20/3/2 | 20/15/10 | 20/4/2 |
| 114 | 25 | 24/22/2 | 24/5/2 | 24/22/12 |
| 115 | 21 | 19/0/29 | 19/0/16 | 19/2/1 |
| 73 | 7 | 2/1/3 | 2/0/5 | 2/0/8 |
| 17 | 12 | 11/0/2 | 11/7/2 | 11/9/36 |
| 8 | 11 | 0/0/16 | 0/0/10 | 0/0/20 |
| 54 | 21 | 21/0/57 | 21/11/12 | 21/0/6 |
| 22 | 8 | 7/0/30 | 7/1/1 | 7/0/30 |
| 41 | 72 | 64/0/98 | 64/29/1 | 64/10/4 |
| 80 | 15 | 13/5/10 | 13/10/1 | 13/5/1 |
| 68 | 8 | 4/0/16 | 3/0/14 | 4/4/0 |
| 109 | 14 | 11/0/7 | 11/1/3 | 11/3/4 |

Chapters found are the same for every method on a book, so the candidates set the ceiling, and the level methods
are judged on chapters below the top and extra. Missed chapters by mechanism:

- A chapter title at the top of its page typed `header` by MinerU and dropped with the page furniture: 73, 68,
  41, 109, 22. General.
- Chapter titles set as pictures: 8. One book.
- OCR in two titles: 115.

Extra chapters by class (front: page 13 or earlier, or within the contents; back: index, notes,
acknowledgements, references, credits; split label: a bare "Chapter n" block beside its title; inside: anything
else within the chapters):

| method | front | back | split label | inside |
|---|---|---|---|---|
| A | 82 | 23 | 15 | 161 |
| C | 34 | 16 | 12 | 21 |
| E | 53 | 6 | 2 | 67 |

Front matter (title page, author, series, publisher, "Contents", "Abstract") is extra on 13 of the 14 books. E's
inside extras are mostly 17 (sections taken as chapters) and 22.

## Changes to E, each measured alone over the 14

| change | moved (found/below/extra) | verdict |
|---|---|---|
| 7: a group of one look ("Глава n") also splits at the 15% size step | 17: 11/9/36 to 11/2/0; extras down on 7, 41, 109 | kept, no loser |
| L: a bare "Chapter n" block takes the next block on its page as its title | 54 A extra 57 to 4, 54 C 21/11/12 to 21/6/1; worse on 113 A (extra 8 to 16), 22 C (found 7 to 6), 54 E (below 0 to 14) | kept with 6 |
| 6: a larger group not picked as the chapters joins them, unless it runs a number | on 7 and L: 114 24/22/12 to 24/0/13, 54 21/14/4 to 21/0/4 | kept, no loser left |
| 9: at most one chapter per page | the whole toc lost on 73, 17, 22, 68 E; 7 A found 10 to 0 | dropped |
| F: only the first block on its page is a candidate | extras fall (22 30 to 2) but found falls on 54, 41, 115, 114, 7 | dropped |
| H: a `header` block first on its page is a candidate | found up on 73, 41, 68, 22, 114, down on 17; extras up on 73 (2 to 23), 68 (4 to 36) | dropped |

## Second gate: failed

Named before any look, read as pictures afterwards: text books 105, 82, 75, 95, 61, 94 (several publishers, two
with parts over chapters; all from one open access collection), scan 9 against the contents the stage placed, and
55 against its own contents titles. E with 7, L and 6, frozen. Bars registered before scoring, per book: found >=
90% of the counted chapters, below the top and extra each <= max(1, 10% of them); the gate passes when all six
text books pass.

| book | counted chapters | found | below the top | extra (service) | bar | result |
|---|---|---|---|---|---|---|
| 105 | 9 | 8 | 0 | 24 (8) | 1 | miss |
| 82 | 4 | 3 | 0 | 14 (3) | 1 | miss |
| 75 | 15 | 14 | 2 | 1 (0) | 1.5 | miss |
| 95 | 5 | 5 | 5 | 7 (0) | 1 | miss |
| 61 | 22 | 22 | 0 | 3 (0) | 2.2 | miss |

Pictures read at 1.4 to 3.7 s a page, so 9 and 94 were left unread. Mechanisms of the misses: front matter
(title, series and publisher pages, contents lines), running heads that carry their page number typed as text
(the number keeps them from the repeat filter; new on the gate), index lines, contributors' names over the
chapters of an edited volume; on 95 the halves of each part ("Part I (A)") took the chapter level. Every book
missed on extras, and front matter is among them on all five. Found holds (>= 90% on 75, 95, 61).

## Where the chapters are lost

A table of every block of at most 15 words on the 19 books read so far (the 14 and the five gate books), with its
type, box, size, place on the page, words below it and the gold it matches. Gold chapters with no block in it: 9, most
of them titles set as pictures (8), OCR (115) or longer than 15 words. So the candidates hold nearly every chapter, and
they are lost after it: of 319 counted chapters, 32 by the candidate filter (most typed `header` by MinerU), 21 in
grouping (a group under 5 members, the size step), 31 at the pick (the chapter in another group than its siblings).

Choosing the chapter group by a shared pattern (word, alignment, place) adds nothing: E already picks the group with
the most gold chapters on 18 of 19. Placement does tell a chapter level from a junk group (high on the page and first
on it in 88-100% of the members of the 13 good groups, 13-54% of the 6 junk ones); as a test on the pick it turns 73,
8, 22, 68, 82 into no toc, losing the 16 chapters found there.

## Line boxes

The converter's middle json drops MinerU's lines. An image built on the stand's MinerU converter keeps each block's
line boxes, used for this measurement only and taken off the stand after it, and 1182 pages of the 19 were read again through it: the pages holding a gold
chapter or one of E's extras, and their neighbours. A line box is free of the text's length, not of its letters: on 114
both chapter titles are 40 pt in the text layer, and the boxes are 44 for ПРЕДИ and 36 for ГЛАВА 11 (the descender of
Д); caps move it too. Over the 19, gold titles within 15% of their book's median: 202 of 227 by the area proxy, 194 by
line height; extra lines inside that band: 38 of 145 and 31. Better on 114, 7, 95, 61, 75, worse on 8, 82, 73: no case
for line height as the size.

## Running heads

A block MinerU types `header` was thrown out unread. It is a guess from the place on the page: chapter titles at the
top of their page get it on 41, 73, 68, 22, 114, 82. Three changes, each measured alone on 6, 7, L over the 19:

| change | what it does | moved |
|---|---|---|
| R | every header block of at most 15 words is a candidate; the repeat filter alone removes running heads | 41 64/10/3 to 72/4/2, 22 7/0/30 to 8/3/1; 68, 82 to 0 found (running heads set on alternate pages escape the repeat filter); 17, 95, 61, 105 lose 1-2 |
| T | repeats counted apart for header blocks and the rest | on R: 17, 95, 61, 105 get back the titles their own running heads had made "repeated" |
| V | the running-head size is the median of the header blocks the repeat filter removed; a header block no larger than 1.15 of it goes too | on R: 68, 73, 82 lose their running heads; 22 untouched |

Two forms of V failed first: the smallest size step (the steps chain, so on 68 92 of 93 candidates make one step, and on
113 the one step was the chapters) and the median of the header blocks kept (on 22 those are all "CHAPTER n").

R, T and V together against 6, 7, L: found +17 and no book loses a chapter (41 64 to 72, 73 2 to 6, 68 4 to 7, 114, 22
+1); extras down on 22 (30 to 1), 41, 1; up on 8 (+5), 73 (+3), 82 (+2), 113, 95, 61 (+1). Every extra they add is a
front-matter line on pages 1-13 that stands once: a series name, "Contents", "Foreword", the author or a logo on the
cover. On 113 the cover's author takes the service role in assembly; on 95 and 61, with unnumbered chapters, it does
not. A cut before the end of the contents is the next change.

One book not looked at before, 21 (O'Reilly, 164 pages, parts over chapters), read afterwards with the probe frozen:
0/0/0 on 6, 7, L; 8/4/1 with R, T and V. All 8 counted chapters found (Preface, Chapter 1, Parts I-III, Index, About the
Author, Colophon); the 4 below the top are Preface and the three at the back, found at a section's level; the extra is
the cover's title. It misses the bar on below the top.

## In the code

E with 6, 7, L, R, T and V is the toc source `headings` (`app/stages/toc/sources/headings.py`, thresholds in
`config/toc.yaml` under `scan_layer.headings`), tried after every other source and before one chapter or "structure
not recognised". It was off by default while the gates ran; after the third gate the owner put it on by default as
the last try before that failure, since it only meets books that would fail otherwise; the book knob
`toc.from_headings` turns it off for one book. A guard measured on every read book: more top entries than half the
pages is no structure (55, the UNIX manual, 0.81 a page; the highest of the rest 0.43). On the 20 books read as pictures it gives the same entries as the probe measured here.

## The front cut

The headings before the end of a contents printed in the first 30 pages are front matter and no candidates; the
contents pages are those the printed-contents source finds, placed or not. With and without the cut, on the 20 books
(found/below the top/extra):

| book | contents | without | with |
|---|---|---|---|
| 73 | 7-8 | 6/0/11 | 6/0/1 |
| 8 | 4-5 | 0/0/25 | 0/0/9 |
| 82 | 13-14 | 3/0/16 | 3/0/3 |
| 105 | 9 | 8/0/24 | 8/0/16 |
| 95 | 9-10 | 5/5/8 | 5/5/4 |
| 61 | 7-11 | 22/0/4 | 22/0/0 |
| 54 | 13-21 | 21/0/4 | 21/0/1 |
| 41, 22, 80, 109, 75, 21 | | 1-2 extra each | 0 extra |

No book loses a chapter; extras over the 20 fall from 118 to 53. 7, 113, 1, 114 and 115 have no contents and do not
move: 114 keeps its 13 front lines, the case where the first chapter has to be found another way.

## Third gate: failed

Named before any of their pages were read as pictures: text 47, 50, 66, 94 (several publishers), scans 119 and 9;
the source as committed with the front cut; bars as the second gate; the stage's own toc with bookmarks off reported
beside it, not as a pass rule.

| book | counted | found | below the top | extra | the stage, bookmarks off | mechanism |
|---|---|---|---|---|---|---|
| 47 | 18 | 16 | 0 | 2 | 16/0/2 | Bibliography and Index found 2-8 pages after their bookmarks, as the stage finds them |
| 50 | 11 | 10 | 3 | 1 | 11/8/0 | three chapters a level down, Index missed |
| 66 | 1 | 0 | 0 | 3 | 0/0/1 | no gold: one top bookmark, "Cover page" |
| 94 | 17 | 13 | 13 | 0 | 14/2/1 | an edited volume: the articles' inner sections, numbered from 1 in each, taken as the chapters; the articles' titles are 23-word document titles, cut by the 15-word limit |
| 9 (scan) | 10 | 0 | 0 | 54 | | chapter titles set as pictures, as on 8; its toc comes from its printed contents anyway |
| 119 (scan) | 0 | 0 | 0 | 173 | | no gold: one bookmark per page (image file names); its lessons come from the label knob anyway |

Every text book misses. Two changes tried after it, each alone on the 20 development books: a chapter label with its
number taken as a heading at any length moved nothing (the long titles carry no label); a running number required to
repeat few of its numbers moved only 68, to 7/0/12 (a loser). Both dropped. A block typed `doc_title` kept as a
candidate up to 40 words: 109 11 to 13 found, 75 14 to 15, nothing else moves; kept. On 94 it finds 16 of 17, all
below the top: the sections stay the pick.

