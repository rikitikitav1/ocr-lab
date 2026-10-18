# 2026-10-18 - Spaces PDFium makes up inside words

Lead: PDFium reads a PDF's text glyph by glyph and puts in a space wherever two glyphs stand far apart.
A heading set with letter spacing ("Г Л А В А") and a word cut by kerning or a broken ligature ("Aircraf t",
"justif ied") come out with spaces inside words, and every reader of the text layer (the page layout, the
running heads, the measures, code from the layer) and both engines inherit them. The question: can the
book's own geometry tell those spaces from word spaces, without a word list, and where does it stop.

Scheme: [diagrams/spacing.drawio.svg](../diagrams/spacing.drawio.svg).

## Setup

**Set** the 47 runs 375 to 421 (46 books; 110 left out, see below). **Ground truth** none: each changed row
is listed and read; hunspell (ru, en dictionaries through spylls) is a report column only, never a judge.
**Signals** per row: whether PDFium generated a space (`FPDFText_IsGenerated`), the gap between the glyphs
on its two sides by the ink box and by the advance (loose) box, the font size from the char matrix.

## Steps

1. **A vocabulary guard, dropped.** The first version joined a run of one- and two-letter tokens into words
   the piece or the layer writes whole elsewhere. Every guard it needed was a frequency guard in disguise:
   formula glue passed through the layer ("swyxswt", "FmFn" on 23), the engines' own glue through their
   text ("решетчатоголабиринта" on 11), and the words a book spaces are its headings' terms, often
   written whole nowhere else, so 11's headings came out half joined.
2. **Glyph gaps, one cut per row.** A generated space at most the row's letter gap (90th percentile of
   tight pairs + 0.3 pt) goes. 341 rows on 9 books, and real harm on 54 and 58: justified prose whose word
   spaces are generated and narrow ("ifyou", "ofa"). The cause was the ink box: side bearings and the f
   overhang inflate the letter gap. hunspell caught the harm (known share down) and misread 11's medical
   terms ("ринофима", "аносмия"), which settled it as a column, not a judge.
3. **Two mechanisms (owner).** A tracked row (every letter apart) and a single split inside a word are
   told apart and get a rule each.
   - Tracked, judged on the whole row by advance boxes: two generated spaces at least, each under 0.25 em,
     under half the row's narrowest word space and under twice its letter gap + 0.3 pt. A run unit cut
     words at PDFium's jitter ("ИЗДАТЕ Л Ь С К А Я"); a token-length test let "Looping a triangle" through
     before the letter-gap anchor closed it.
   - Split, by ink boxes: one generated space between letters at the row's own letter gap + 0.1 pt, on one
     visual row (a PDFium row may wrap: a gap of −160 pt joined "продукцииПродажи" before that check).
4. **Where geometry ends.** An f overhangs its advance in ink and in the loose box alike, so "of functions"
   (a word space) and "justif ied" (a broken fi) have the same gap with opposite truths. No split is joined
   next to an f; those wait for the judge below. Rows with a math symbol (Unicode Sm) or a private-use glyph
   are skipped until the formula element marks formula regions (owner).
5. **The reader in `pdf.py`.** Beside the older fix for line breaks inside words, so every reader of the
   layer sees the joined row. Old and new reader over the shelf: rows changed on 11 (240), 72 (22),
   112 (21), 23 (12), 20 (6), 111 (4), 29, 19, 8; none on 54, 58, 4, 17, 48, 3. Reading the layer costs up to
   twice as long on books with such rows.
6. **The engines' side.** An engine block holding the row's letters, whatever its own spacing, takes the
   joined row: on 11, 114 blocks (some engine text was already joined, some half: "О томикоз").

## The judge, a prototype

A small character tagger trained on the shelf's rows without generated spaces was tried for the splits geometry
cannot settle (next to an f). It was good in English, where most of its rows were, and did not carry to languages it
had not seen (delete precision 0.96 in English, 0.92 in Russian, 0.58 to 0.81 in French, Bulgarian and Ukrainian), so
it was not built; the splits by an f are settled by the book's own words (the last section).

## Not covered

110 is a scan whose OCR layer has loose boxes: the gaps carry no signal there ("cate g o rie" and
"Porţ iiOtomane" on both sides of any cut). It waits for an OCR cleanup stage, where a judge of the same
kind, trained with character noise too, is the start.

## The gate on the shelf

The structure moved where it should (8 and 11 read their contents entries joined) and the page layout only on 77 (its
spaced running head). The reassemblies failed: the referee picks an engine per page by word agreement with the
layer, and the joined layer flipped the pick on 10 pieces of 11 to the engine with worse heading markup ("7 .1 .
ОСТРОЕ…", piece 87 with 20 headings where it had 38), so sub-entries found fell by 53, while lost words fell by 9922
over the shelf. 110, an OCR layer, was joined too. The reader is taken back out until the picks are kept apart from
the change and OCR layers are told apart.

## The reader back, second version

The referee and the assembly passes now read the layer as read, so the joined rows cannot move the picks; the
measures, the page layout and the structure read it joined, all from one pass over the page. A file is joined only
when its letter gaps (90th percentile, in em) stay under half its word gaps (10th percentile), stamped per file in
the report: the joined files of the shelf reach a ratio of 0.27 at most, 110 (an OCR layer) sits at 0.70 and 126 (a
Hebrew dictionary set right to left) gives negative word gaps, and both are read as they are. An engine block takes
the joined row only where the join takes spaces out of its text: on the first run it also put the layer's own space
into headings the engine had right ("8.1. ОСТРЫЙ" became "8 .1. ОСТРЫЙ").

Gate: structure moved on 8 and 11 only, the page layout on 77 only; over 47 reassemblies the picks stayed byte for
byte, the subsections found and the running heads did not move, rows were joined in engine text 94 times, lost words
fell by 372 (11: 261, 112: 87). Extra words rose on 11 by 468 with its text the same: the measure now reads the
joined layer against engine text that keeps letter spacing in rows mixed with other text, which the reader leaves as
the engine wrote it.

## Splits by an f, checked against the book

A split next to an f ("def inition", "justif ied", "Aircraf t") passes the gap test as often as a word space before
"f" does ("log f", "If f is"), so the gap alone cannot settle it. The rule: such a split is joined only when the book's
own layer sets the joined word solid more often than the rarer of its two halves stands alone; otherwise the space
stays as read. A first form, joining whenever the joined word was met solid at all, joined junk (26 "f o" to "fo" in
104 places, 62 "Gulf News", 74 "lex fori").

Probed offline over the 125 books: 72 joins its 13 splits ("def inition", "justif ied", "f irst", "suff icient"), 20
its 2 ("Aircraf t"), 26 its 13 (letter-spaced Pascal code, "Sizeo f" to "Sizeof"), all read right; every other book's
layer text stays byte for byte. Gate on 72 and 20: text moved only where the joins are, lost words 662 to 660 and 863
to 860, headings, subsections found and nodes out of order unchanged.
