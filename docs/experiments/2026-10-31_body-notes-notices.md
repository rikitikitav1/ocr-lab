# 2026-10-31 - The elements stage, one body learner, notes and foot notices

**Question.** Can the layouts move into one stage of the book's elements with no change of output, and can one body
size, read after the running band, give notes on the intersection of their factors and take a repeated notice out of
the text?

**Outcome.** The move changed nothing. The body learner finds the notes block on three books that had none, and the
notices leave the text of the two books that carry them. The price: 71 loses top nodes with the contents off, and a
few real notes stay out, named below.

## The move

Each layout is now keyed by the modules it reads, so an edit of one no longer makes both stale. Gate written before the
run: every layout learned again the same, no reassembly moved, no structure touched.

| check | job | result |
|---|---|---|
| layouts learned again | batch 43899 | 125 page and 123 heading layouts, 0 learned other |
| `reassembly_gate` | 44030 against 43840 | 0 of 47 moved |

## One body learner

The body size is the style of the first three lines of four words or more under the running band, the mode over the
pages, kept only when it sets a quarter of the book's characters. Before, it was the style with the most characters.

Learned other on 71, 74 and 93 (body 9, 8, 8 to 10), and each now finds a notes block where it found none: 71 6764
lines on 466 pages, 74 6609 on 273, 93 3245 on 187. The GoalKicker series moves from 9 to 10 too, because its code
outweighs its prose.

Tried and dropped: a rare size as a heading size. It brought 71 back, 7 of 7, and dropped precision on 52 from 1.0 to
0.517, and on 2, 61, 23, 57, 3 and 113: captions and table heads are rare large sizes too. A floor of ten pages for
notes also went, since a book may set five notes in all.

## Notes on the intersection of factors

A note stands below the last body line, smaller, after a gap over 1.3 body steps, and opens with a number or a star
that its page's text cites. Each mark opens one note, and numbers run in order from page to page or restart at 1. A rule
above the notes is no factor: on 74 and 41 the rules frame the page's foot on every page alike.

| gate | job against base | result |
|---|---|---|
| `structure_gate`, nothing off | 48160 against 44209 | 0 of 125 moved |
| contents_off | 48161 against 44208 | found -4, extras -83; moved 71, 74, 93 |
| reassembly | 48162 against 45893 | 19 of 47 moved, text only on 1, piece 92 (20 words) |

`structure_gate` with nothing off cannot see notes, because those books route to bookmarks or a contents, and the
reassembly set holds none of the heavy-notes books (71, 74, 83, 104). So these gates say little for the rule itself;
the blocks above were read on the layouts.

| contents_off | before | after |
|---|---|---|
| 74 precision | 0.196 | 0.348 |
| 93 precision | 0.544 | 0.987 |
| 71 found | 7 | 3 |
| 71 extras | 83 | 0 |

71 moves because its heads at 12 are 1.14 times a body of 10.5, under the 1.15 `text_larger`.

Named losses: 1 (a chapter-end note whose reference stands on another page, 20 words set aside by an engine and gone),
64 (references run through the book, notes restart per page), 129 (notes run into the body). A lone numbered note stays
out of order: relaxing that moves 9 books, the last three of them likely wrongly.

## Foot notices

The same text at one place on many of a book's pages is page furniture, whatever its line count, and leaves the
assembled text. The share is of the book's pages, at 0.25, in a gap: 74 at 0.88, 59 at 0.43 or more, book 15 at
0.06, 102 at 0.04, 8 at 0.01. A first try took the share of the feet: a book with few feet passes on anything, and that
round failed its registration on 8, 10, 125, 129 before any gate was read.

| gate | job against base | result |
|---|---|---|
| layouts | | notices only on 59 and 74 |
| `structure_gate` | 50180 against 48758 | 0 of 136 moved |
| contents_off on 59, 74 | 50181 | no change |
| reassembly | 50376 against 49123 | 0 of 48 moved |

| fresh run | before | after |
|---|---|---|
| 74 (446 against 443), licence lines | 201 | 33 |
| 74, words | 238311 | 228572 (168 licences of 58 words) |
| 59 (447 against 444), "OPERATING SYSTEMS" | 191 | 26 |

What stays: a page with no body-size line claims no notice (74's tables of cases), and 74's recto words and changing
copyright year.
