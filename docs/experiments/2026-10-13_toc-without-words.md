# 2026-10-13 - The book's structure without word lists, as a tree, and its layout

## Outcome

The toc stage used to find a printed contents page by a heading word ("Contents", "Содержание") and parts and
chapters by label words ("Part", "Глава"), all from lists in `config/toc.yaml`. A book in another language, or one
headed "Table of Content", was silently missed. In the code now: contents pages are found by shape (numbered lines
whose page numbers rise and reach across the book), the heading word's other roles (running head, folio line,
block heading, a bookmark named as a contents, the scan's heading) go by repetition, place and page, and
`contents.headings` has left the config. The structure is a tree of nodes with parents and depth; the engines
read the book by tree level, and a boundary page between two pieces is cut once for both sides. Contents rows
split over bookmarks, run together on one line or set with labels in their own column are rejoined or split. A
page layout (running heads, folios, notes, heading styles by level) is learned from each book and runs as a stage
over the whole shelf. Taken back: parts told by the numbering under them (the owner: no numbers) and part and
chapter labels learned from the book (the gate failed); the label word lists stay for now.

## Setup

- Shelf: 125 books, 115 with a text layer and 10 scans. Before each change the shelf's toc or structure was
  collected on the code just before it and a shelf snapshot taken; after the change everything was collected again
  and compared. A first snapshot built from tocs of older code was unfair and was replaced (snapshot 2 on).
- Gate, registered with the auditor before each run: the books allowed to move are named from their pages, any
  other mover is a loser read by mechanism. Text changes are measured as pairs: a control run on the old units
  against a run on the new code, or every kept run reassembled from its readings.
- Scripts and tallies are in `temp_files/` (`exec_*`, `audit_*`); the layout model is in
  `~/working_docs/projects/ocr-lab/notes/book_layout.md`.

## What was tried

| step | change | gate | what moved | verdict |
|---|---|---|---|---|
| 1 | contents pages by shape: runs of pages with 3 entry lines, numbers rising (70% of steps), inside the book, reaching a third of it | toc vs snapshot 1 | offline 99 of 115 agree with the word rule; live 13 of 125 moved, lists after the contents entered tocs (80: 1 to 59 extra chapters) | taken back |
| 2 | the same, plus a block split between pages and the contents pages up to the winning block | snapshot 2, 3 | 15 moved: lists left 61, 74, 25, 71, 77; 105 recall 0.69 to 1.0; 30's chapter 2 back on page 10 | kept |
| 3 | running head by repetition, a folio line by its number, first and last lines by place, no word | snapshot 4, 5 | 73 and 89 lose a heading row; 8 is the named loser (heading below imprint lines) | kept, 8 open |
| 4 | a bookmark named as a contents is told by its page, not its title | snapshot 7 | 122 new tocs, none moved; 72 keeps "Table of contents" over its chapters | kept |
| 5 | the scan's heading word: a running head by repetition, a line the next one repeats opens nothing | snapshot 8 | 122 new tocs, none moved; `contents.headings` left the config | kept |
| 6 | probe: part and chapter lists emptied | snapshot 9 | 30 of 122 moved: the words tell where a book is cut (23 books) and a chapter's depth without indents (3) | probe |
| 7 | parts by nesting: a top entry whose numbered children run on from the previous one | snapshot 10 | 92 as registered, plus 46 by accident | taken back |
| 8 | the tree: every node's parent, every version's depth | snapshot 11 | 122 new versions, none moved | kept |
| 9 | each node pinned to the heading closest to its title, one heading per node | 56 books reassembled | no text moved; heading levels on 26 books, 124 units, 322 lines (the old first fit) | kept |
| 10 | the engines read by tree level 0; a node over 100 pages split into its own pages and its children | control vs run pairs | no node lost; see the table below | kept, default |
| 11 | a boundary page kept whole by the piece that only re-reads it | runs reassembled | 49 gets its page back, repeated paragraphs grow (49 22 to 109, 23 16 to 107) | taken back |
| 12 | one cut per boundary page, both pieces parsing the next piece's readings | runs 199 to 222 reassembled | repeats up nowhere; 4 +174 words (epigraphs), 49 +686 | kept |
| 13 | page layout learned per book: slots, folio, notes, heading style per level | probes on 3, 72, 6, 16; shelf of 110 | levels that hold 200 of 306 (run 1) to 218 (run 6) | kept as a stage |
| 14 | the layout stage over the shelf overnight | against probe run 6 | 115 page layouts equal, 0 differ; 223 of 309 levels hold | kept |
| 15 | in a pinned pair the line closer to the title is the heading | shelf probe | 222 levels hold (218), worse on 49, 51, 75, 77, 81 | not a default |
| 16 | contents rows: A titles split over bookmarks joined, B rows on one line split, C a lone label closes its row | dry and live gates | A only 107 (424 to 415 rows); B only 50 (151 to 182); C the nine books named (104 94 to 293) | kept |
| 17 | part and chapter labels learned from the book | snapshot 17 | 18 books, covered ones among them (59, 92, 64, 66, 81, 95) | taken back |
| 18 | a node's own outline on its opening page (an edited volume's article) becomes its children, levels by indent | snapshot 18 | 85 32 to 214 rows, 88 27 to 328, 89 317 to 350, all of this shape; 72's contents page under a bookmark named "Table of contents" also folded, then left out with the book's contents pages | kept |
| 19 | a piece's read job leaves its tail page to the next piece, the assembly takes it from that reading | kept runs 199 to 222 reassembled; live runs 223 to 226 (38, 68, 73, 49) | old runs: every piece's numbers and text as before; live: lost, extra and layer words, blocks and sections equal on every piece, the tail page never missing; set-aside furniture lower (the page no longer read twice) | kept |
| 20 | a re-read boundary page measured as the next piece's own, less the tail the earlier piece took | 112, 10 (chapters open mid-page) and 20, 31, 38 (they do not), then all 47 runs | lost 112 0.089 to 0.009, 10 0.099 to 0.015; 20, 31, 38 unchanged or lower; bundle text byte-identical | kept |
| 21 | a short line over the next title that ends no sentence ("Chapter 7", "ЧАСТЬ I") stays below the cut, and the title an engine reads again under it is dropped | 47 runs against step 20's; movers registered: 4, 5, 11, 15, 20, 23, 45, 48, 49, 54, 65, 118; tails of 112, 10, 111 to stay | the registered twelve moved, tails stayed; 50, 80, 110 also lost a title read twice; lost, extra, subs, duplicates equal on all 47; out of order 4 0.001 to 0.005 (the raw run's), 15 0.016 to 0.015 | kept |
| 22 | a node keeps every level the book gives it; only the Markdown caps headings at 6 | snapshot 20 after a recollection on the code before; may move: 71, 85, 87 to 92, 103, 104, 106 (a node at 6 or a source deeper), levels only | 87, 88, 90, 103, 104 moved, each only its level-6 nodes to 7 (3, 15, 5, 18, 60), titles, pages and rows the same; nothing else moved; run 422 of 87 writes them as `######` with `level=7` in the node comment | kept |

### Reading by tree level

Pairs where the reading moved most, controls the old units. Words are the bundle's word count,
duplicates its repeated paragraphs.

| book | words, control to run | duplicates | reading |
|---|---|---|---|
| 67 | 111925 to 162027 | 114 to 0 | pages 68 to 219 the old units never read; a chapter written twice before |
| 95 | 69487 to 124678 | 0 to 0 | pages 29 to 88 and 157 to 222 never read before |
| 71 | 259327 to 285098 | 0 to 0 | its never-read pages back |
| 18 | 544809 to 498882 | 87 to 0 | the old units read some parts' pages over their chapters |
| 16 (scan) | 108890 to 107563 | 14 to 1 | eight chapter openings written twice before |
| 49 | 31266 to 31260 | 17 to 17 | after the boundary fix; before it 30577 words, lost_text 0.187 |

### Before and after: the raw run's books

The 47 books of [the raw run](2026-10-11_raw-run.md), each run again on one code after step 21 (runs 375 to 421)
from its kept readings, so only the assembly and the measures ran again. Before is the raw run's last run per book,
chapters its units; after, nodes is the tree and pieces the units the engines read. One value means no change.

| book | runs | chapters → nodes, pieces | subs found | lost | extra | duplicates | out of order |
|---|---|---|---|---|---|---|---|
| 1 | 96 → 418 | 21 → 375, 21 | 354/354 | 0.005 | 0.005 | 0 | 0.0 |
| 2 | 77 → 405 | 26 → 177, 24 | 151/151 → 153/153 | 0.01 → 0.009 | 0.009 | 0 | 0.002 |
| 3 | 78 → 404 | 23 → 224, 5 | 201/201 → 219/219 | 0.037 | 0.007 → 0.006 | 0 | 0.001 |
| 4 | 97 → 375 | 24 → 310, 24 | 286/286 | 0.002 | 0.002 | 0 | 0.005 |
| 5 | 98 → 376 | 19 → 270, 19 | 259/270 → 250/251 | 0.014 → 0.015 | 0.004 → 0.005 | 0 | 0.002 |
| 7 | 80 → 409 | 11 → 11, 11 | - | 0.002 | 0.0 | 0 | 0.0 |
| 8 | 81 → 413 | 12 → 73, 12 | 48/58 → 48/60 | 0.029 | 0.055 | 0 | 0.001 |
| 10 | 82 → 388 | 23 → 24, 13 | - → 10/10 | 0.015 | 0.009 → 0.001 | 0 | 0.004 → 0.001 |
| 11 | 83 → 380 | 17 → 138, 12 | 55/121 → 56/126 | 0.046 → 0.045 | 0.225 → 0.224 | 0 | 0.001 |
| 12 | 84 → 391 | 1 → 1, 1 | - | 0.0 | 0.005 | 0 | 0.0 |
| 14 | 86 → 392 | 1 → 1, 1 | - | 0.029 | 0.058 | 0 | 0.0 |
| 15 | 87 → 381 | 8 → 8, 8 | - | 0.037 | 0.053 | 0 | 0.015 |
| 17 | 70 → 400 | 13 → 96, 13 | 82/82 | 0.007 | 0.003 | 0 | 0.0 |
| 18 | 99 → 408 | 63 → 1011, 103 | 937/948 → 896/908 | 0.005 | 0.006 | 87 → 0 | 0.052 → 0.049 |
| 19 | 100 → 407 | 29 → 171, 29 | 141/141 | 0.019 | 0.013 | 0 | 0.018 |
| 20 | 65 → 377 | 12 → 88, 12 | 72/76 | 0.022 → 0.021 | 0.005 | 0 | 0.0 |
| 21 | 69 → 395 | 23 → 130, 9 | 104/104 → 117/120 | 0.022 | 0.009 | 0 | 0.003 |
| 23 | 67 → 385 | 20 → 143, 20 | 122/122 | 0.043 | 0.031 | 4 | 0.001 |
| 29 | 72 → 390 | 1 → 1, 1 | - | 0.019 | 0.023 | 0 | 0.001 |
| 31 | 137 → 420 | 70 → 379, 70 | 304/307 → 302/307 | 0.003 | 0.005 → 0.008 | 0 | 0.002 |
| 38 | 89 → 421 | 32 → 125, 32 | 83/91 | 0.003 → 0.002 | 0.007 → 0.01 | 0 | 0.003 |
| 40 | 74 → 394 | 34 → 125, 34 | 89/89 | 0.001 | 0.006 → 0.01 | 1 | 0.001 |
| 43 | 131 → 396 | 65 → 281, 65 | 212/214 | 0.005 | 0.004 → 0.006 | 1 | 0.003 |
| 44 | 129 → 402 | 38 → 200, 13 | 161/161 → 169/186 | 0.02 | 0.012 → 0.011 | 0 | 0.006 |
| 45 | 75 → 382 | 25 → 154, 25 | 129/129 | 0.024 | 0.008 | 0 | 0.005 |
| 48 | 90 → 379 | 38 → 361, 31 | 322/323 → 329/330 | 0.056 | 0.019 | 0 | 0.004 |
| 49 | 73 → 383 | 16 → 16, 16 | - | 0.002 | 0.004 → 0.006 | 17 | 0.005 → 0.003 |
| 50 | 130 → 414 | 25 → 182, 20 | 89/126 → 160/162 | 0.045 | 0.004 | 0 | 0.093 → 0.094 |
| 52 | 132 → 401 | 22 → 150, 19 | 127/128 → 130/131 | 0.002 | 0.005 | 0 | 0.001 |
| 54 | 66 → 378 | 23 → 241, 23 | 218/218 | 0.008 | 0.002 | 0 | 0.005 |
| 58 | 76 → 412 | 15 → 98, 15 | 83/83 | 0.022 | 0.034 | 0 | 0.001 |
| 65 | 136 → 384 | 11 → 12, 11 | - | 0.005 | 0.007 | 1 | 0.0 |
| 72 | 135 → 398 | 13 → 13, 13 | - | 0.01 | 0.013 | 2 | 0.001 |
| 73 | 62 → 419 | 19 → 32, 9 | 12/13 → 18/23 | 0.022 → 0.025 | 0.003 → 0.004 | 0 | 0.048 → 0.034 |
| 80 | 61 → 411 | 19 → 19, 17 | - → 0/2 | 0.004 | 0.001 | 0 | 0.004 |
| 110 | 91 → 417 | 12 → 41, 12 | 16/29 | 0.42 | 0.374 | 0 | 0.011 |
| 111 | 92 → 389 | 8 → 28, 8 | 1/19 | 0.044 | 0.041 | 0 | 0.16 → 0.149 |
| 112 | 63 → 387 | 38 → 39, 38 | - | 0.009 | 0.007 → 0.005 | 0 | 0.027 → 0.023 |
| 113 | 93 → 399 | 25 → 25, 25 | - | 0.0 | 0.001 | 0 | 0.0 |
| 114 | 71 → 403 | 26 → 26, 26 | - | 0.0 | 0.001 | 0 | 0.0 |
| 115 | 94 → 406 | 22 → 22, 22 | - | 0.002 | 0.005 | 0 | 0.001 |

| book | runs | chapters → nodes, pieces | subs found | agreement | duplicates |
|---|---|---|---|---|---|
| 6 | 79 → 410 | 23 → 95, 18 | 72/72 → 77/77 | 0.862 → 0.86 | 0 |
| 9 | 64 → 415 | 11 → 11, 11 | - | 0.385 | 0 |
| 13 | 85 → 393 | 1 → 1, 1 | - | 0.921 | 0 |
| 16 | 88 → 416 | 17 → 188, 9 | 164/171 → 172/179 | 0.912 → 0.911 | 14 → 1 |
| 118 | 68 → 386 | 86 → 88, 66 | - → 16/20 | 0.1 → 0.102 | 5 → 1 |
| 119 | 95 → 397 | 18 → 19, 18 | - | 0.667 | 1 |

- Measured first on runs 223 to 270, a mid-page chapter opening showed as loss (112 0.089, 10 0.099, 23 0.056, 111
  0.058, 18 0.012): the measure gave the earlier piece's tail to nobody. Step 20 fixed the measure, not the text.
- Duplicates: 18 87 to 0, 16 14 to 1, 118 5 to 1.
- Subs: 50 89 of 126 to 160 of 162 (rows on one line split, step 16); 44 has 186 sub-entries now and 17 are not
  found as headings; 5 and 18 count fewer sub-entries (270 to 251, 948 to 908), not looked at.
- Extra grows by 0.002 to 0.004 on 31, 38, 40, 43 and 49: on 43 that is 87 words over 65 chapters, three at most in
  one; not looked at.
- A label set above a chapter's title ("Chapter 1" over "1 Data-Oriented Design") went with the tail to the
  previous chapter on twelve books after steps 12 and 19; step 21 keeps it with its chapter.

## The steps in plain words

**Contents pages.** The first shape rule found the right pages but let lists of tables, maps and cases after the
contents into the toc, because the parser only opened a new block at a heading word. Splitting blocks where the
pages stop being adjacent or the numbers start again let the fullest block win alone. The other roles of the word
went one at a time; a heading drawn as a separate object comes last in PDFium's order (92 of 779 contents pages),
so first and last lines are taken by place.

**Parts and chapters.** Emptying the lists showed what the words do: they say at which level the book is cut, and
give a chapter label its depth where the contents has no indents. Parts by numbering failed its gate on 46 and was
dropped by the owner before the second try was read: a chapter number may be a word, missing or stray.

**The tree.** A book became a tree of nodes with levels, read by level 0, a parent assembled from its own text and
its children. Pinning each node to its closest heading removed the old first fit; reading by level brought back
pages the old units never read and removed their doubles. A boundary page read by two pieces was cut by each side
on its own reading and lost or doubled text; now the cut is made once, from the next piece's readings.

**Layout.** Each book's running heads, folios, notes and heading styles are learned from the book, none set by
hand. On scans a size is a box's area per character, and a line is told from a picture by its box, not the
engine's type. Probes ran on 3, 72 and two scans, then on 110 books in six runs, each change against the run
before; the stage repeats run 6 on all 115 books with a layer.

**Contents rows.** Three mechanisms, each with its own dry and live gate: a title split over bookmarks (107), rows
run together on one line (50), labels in their own column (legal theses on one press: 68, 71, 73, 79, 90, 96, 97,
104, 106). Each live gate moved only the books named.

**Labels learned from the book.** A word met before a rising number on three lines or more was to open chapters,
a rarer one before them parts. It moved 18 books, covered ones among them; a second try moved 47 in a dry pass.

| mechanism | books | what happens |
|---|---|---|
| a running head with its folio read as a label | 17, 64 | "Preface 11", "Введение 2..10" rise with the page and pass as chapters |
| a cross reference at a page's top ("see Chapter 8") | 18, 50, 92 | chapter numbers stop rising, "Part" is learned as the chapter label, every level below shifts |
| a part after the first chapter | 21, 44, 103 | the rule wanted parts before the first chapter and dropped them |
| a label met once or twice, or a number in words | 14, 15, 62, 64, 67, 95, 100 | "ЧАСТИНА I", "CHAPITRE", "Part One": nothing to learn from without a list |

## Open

- Labels from the book, one measured piece per mechanism above; the label lists stay until then.
- "Глава 1." above "1.1." in a contents without indents (2, 11, 53): kept by the label lists today, it comes back
  with labels learned from the book.
- Book 8: a contents heading below imprint lines told from a part title by shape.
- Rows left after step 16: 107's printed wrap, 73's "Part V." alone, 104's titles ending "sect. 1".
- A label ending with a full stop ("Глава 1.") still reads as the tail's last line at the boundary cut.
- A boundary page the two sides read with different engines (28 of 354 boundaries of runs 199 to 222).
- The layout: whether a level's style disagreeing with its pins can be a signal back to the tree; 120's guide
  words as a slot (one book, a knob if it stays); 107's contents rows split mid-title cost 15 node comments.
