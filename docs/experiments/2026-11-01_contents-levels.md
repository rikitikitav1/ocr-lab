# 2026-11-01 - A contents' levels from its numbering, and the word lists gone

**Question.** Can a printed contents give its levels from what it prints, with no word lists, and is the structure
better or worse for it than in October?

**Outcome.** Better. Levels are the gain, far fewer top nodes sit below the top, and no book lost a chapter on
`bookmarks_off`. The part and chapter word lists are gone. A book with a contents or bookmarks now takes no new labels or chapters from
its text (a node's own outline on its opening page still gives its children), and that has a price: on 64 its parts are gone (flat bookmarks, a contents setting its pages before the titles).

## Before and after

Same books in both columns (books added since are left out). `bookmarks_off`: job 22209 (15 October) against 64821, 82
books. `contents_off`: job 43540 (25 October, the first run of that set) against 64822, 107 books.

| | `bookmarks_off` before | after | `contents_off` before | after |
|---|---|---|---|---|
| top nodes found | 1899 of 1979 | 1909 | 2161 of 2888 | 2161 of 2895 |
| found, but below the top | 755 | 62 | 293 | 183 |
| extra top nodes | 71 | 49 | 573 | 451 |
| books whose levels rose / fell (by over 0.02) | | 39 / 4 | | 43 / 7 |

`contents_off` has no contents to read, so most of its gain comes from other work since 25 October, not from these rules.

Held-out set, named before any tuning and scored once: 24, 37, 42, 77, 86 up, 3 unchanged, 50 and 107 mixed; 96 had been
read during the work and is out. The set is spent, so the next tuning on levels needs a fresh one.

## Books that moved most, `bookmarks_off`

| book | chapters found | extra | level agreement |
|---|---|---|---|
| 33 | 107 of 109, same | 0, same | 0.003 to 1.0 |
| 39 | 204, same | 0, same | 0.01 to 1.0 |
| 97 | 10, same | 2 to 1 | 0.047 to 1.0 |
| 87 | 6, same | 2 to 1 | 0.031 to 0.994 |
| 104 | 3 of 6, same | 0, same | 0.053 to 0.986 |
| 103 | 10, same | 0, same | 0.048 to 0.983 |
| 71 | 7, same | 11 to 3 | 0.031 to 0.974 |
| 90 | 6 to 7 | 0, same | 0.065 to 0.863 |
| 81, 64, 18 | 4 to 19, 0 to 34, 42 to 55 | | no contents found: the text's headings, other work since October |

## Worse

| book | what | why |
|---|---|---|
| 85 | level 0.85 to 0.26 (0.995 before the labels change), though entries matched 20 to 204, recall 0.079 to 0.806 | two author rows at their own indent make a level between "A." and the articles, so all below stands one too deep; goes with a part told from an author by face |
| 89 | entries matched 167 to 50, recall 0.524 to 0.157 | duplicates that hit the right page went away; the offset under a broken layer is off by two |
| 102 | level 0.545 to 0.154 | few entries matched; recall stays about 0.07 |
| 84 | level 0.479 to 0.095 | entries right: the bookmarks' top level is the file's name |
| 75, 95, 69 | extra 2 to 5, 2 to 4, 2 to 11 | 75, 95 gained chapters too (12 to 13, 3 to 5), their extras not read; 69: its list of tables is read as the contents |
| 64 | parts gone with nothing off | bold capitals with no page; flat bookmarks; its contents sets page numbers before the titles |

`contents_off` worse: 71 found 7 to 3, 81 21 to 19, 110 1 to 0; extras 0 to 44 on the dictionary 125, 0 to 8 on 113 and 114.
Not every one of these comes from today's rules.

## The rules

A series starting again at one names its parent, the line before each start, so forms nest in the book's own order. A
word before different numbers is a label; the rarer that breaks up the commoner stands above it. Pieces on one height
are one line. A line opening with its own number or label starts an entry. See `app/stages/structure/sources/series.py`.

Tried and dropped: capitals as a level (on 4 the "capitals" are the font Cinzel, on 19, 23, 26 the look already held the
levels, one strayed line split a level); learning labels from every page's head on a book with a contents.

Also tried and dropped: page numbers set before the titles, for 64 alone. It read notes as contents, cost other books
their levels, and one book is no case for a default. 64's parts go with the line's face, like 67's.

Subheadings outside the contents ("Model 1" on 60) wait for filling the branches, chapter by chapter.
