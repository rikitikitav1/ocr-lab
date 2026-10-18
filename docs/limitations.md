# Known limitations

What the measurements found and the stand does not fix yet. Each line names the books it was seen on,
so a later change can be checked against them; the numbers are the books' ids in
[books.md](books.md). The measurements behind them are in
[experiments.md](experiments.md).

## Structure

| limitation | seen on |
|---|---|
| When bookmarks and the printed contents disagree on a page, the printed page wins (the printed contents is the base); the bookmarks were right in 5 of 6 such conflicts on 71 and 4 of 5 on 101. 188 such conflicts sit on 14 books, 142 of them on 89; who is right on the other 12 books is not checked yet | 71, 101, 89 and 11 more |
| Reading a contents spread over several pages made one book worse: a doubled "Chapter 1" row, two "Introduction" rows lost, five rows four pages late, dot leaders left in titles | 101 |
| The contents parser makes entries of author names and wrapped second title lines, and a drifting offset (+9 to +11) leaves entries unverified; the structure itself is right by the bookmarks | 94 |
| A wrapped label leaves a junk row ("Chapter §"); a layer's "III" read as "Ill" leaves another | 71, 87 |
| A number in words is any word after a part or chapter label of the numbering lists, so "Part of Speech" or "Chapter Summary" read as numbered | none seen on the shelf |
| Service roles are not given when the numbering starts after the first 15% of the pages, which leaves short books with a long foreword without them | 68, 96, 75 |
| A scan, or a text book whose layer sets no headings apart (or sets them in letters its languages do not write, a broken layer), with no bookmarks, printed contents or labelled chapters, takes its nodes from the headings of its pages read as pictures; not served are chapter titles set as pictures, and a reference manual whose every subhead looks alike, which fails as "structure not recognised" (more than one node to two pages) | 8, 9 (pictures), 55 |
| Chapters labelled by ordinal words ("درس اول", lesson one) need a book knob naming the word; image-file bookmarks need a knob to be ignored | 119 |
| A dictionary's units are its letters; nothing reads them | 116 |
| Right-to-left printed contents were never seen on the shelf, so their parsing is untested | none |
| Sections whose heading opens with a decorative initial come out garbled in the text layer ("jVîeseriile" for "Meseriile") and are not matched to the structure: 1 of 19 sub-entries found | 111 |

## Text and elements

| limitation | seen on |
|---|---|
| A table is chosen whole from one engine's grid; no cell is repaired, so a table both engines drew badly stays bad | converter_gold sections |
| A table only one engine drew is left out (joining it duplicated text in a measured section) | postgres_ru_prose_00 |
| Code boxes only one engine drew are not added (off after measurement) | converter_gold sections |
| Formulas have no measured scheme yet; images with captions are measured (13 captions set as headings, 36 merged into a paragraph on 41 books) and running heads leak on 11, 23, 48 | all |
| Recognition mixes scripts when several are allowed: Farsi text with Latin and katakana letters ("ämروز", "الアン") | 119 |
| Romanian diacritics split into single letters by the engines count as lost and extra text (about 4% each way) | 111 |
| The running head on the first page it appears is read as a chapter's opening title, so it counts as lost text there | 38 |
| Page thumbnails of other books are recognised as footnotes on a layerless page; they show only in the "words from pages the layer check does not see" number | 38 page 74 |
| The code passes (code rebuilt from the layer, monospace paragraphs as code) are on only in the `technical` preset, which a run takes when the page layout finds 2% of the letters in a monospace face on 5 pages or more; a book with less code gets none of them unless a profile or the book knob `run.preset` says so | all |
| Docling's default backend renders MRC (masked) scan pages black and returns them empty without an error | 9 |
| Docling's paragraph order within a page can be wrong (paragraphs and footnotes swapped), and the page referee takes Docling on a tie | 73, 112 |
| Word measures split on `\w+`, so a run of CJK is one word: agreement and the referee's picks mean little there | 118 |
| Agreement does not tell an empty engine from a disagreeing one | 9 |
| MinerU is the scan engine by default; Docling reads the scanned text only when the run knob `assembly.scan_engine` names it | all scans |

## Metadata

| limitation | seen on |
|---|---|
| "1st Edition" and the series are not read from the copyright page | 71 |
| The language detector read a scanned Chinese course as Russian (confidence 0.9), so a run would give the engines Russian OCR data instead of Chinese | 117 |
| The edition is compared with the volume as text, so "4th" against "4" would slip through | none seen |
| Edition or publisher left empty where the model was not trusted (accepted losses) | 3, 4, 5, 6 |

## Report

| limitation | seen on |
|---|---|
| Scanned ranges carry the engines' agreement and the dictionary share, but no engine confidence (neither engine gives one) | all scans |

## Where it was tried

One machine (see the README) and the languages in the README's table. Nothing was run without a
discrete GPU.
