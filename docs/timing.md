# Time per page

Time per page on this machine, from the job times of the raw run of the shelf
([experiment](experiments/2026-10-11_raw-run.md); 43 books, 14069 pages). Each book's time is summed per phase
and divided by its pages; a chapter's reading is its first, uncached one. Job time only: the card's handovers and the
wait in the queue are not in it.

Books with a text layer, 37 books, 12735 pages:

| seconds per page | min / median / mean / max |
|---|---|
| MinerU reading | 0.60 / 1.08 / 1.43 / 3.88 |
| Docling reading | 0.20 / 0.77 / 1.58 / 8.20 |
| assembly | 0.03 / 0.19 / 0.21 / 0.67 |
| bundle and report | 0.00 / 0.01 / 0.02 / 0.14 |
| whole book | 0.95 / 2.16 / 3.25 / 11.90 |

Scans, 6 books, 1334 pages:

| seconds per page | min / median / mean / max |
|---|---|
| MinerU reading | 1.36 / 1.92 / 2.68 / 6.67 |
| Docling reading | 1.89 / 5.90 / 5.87 / 9.83 |
| assembly | 0.02 / 0.08 / 0.09 / 0.19 |
| bundle and report | 0.01 / 0.03 / 0.03 / 0.06 |
| whole book | 3.39 / 7.98 / 8.67 / 16.60 |

A whole text-layer book took 1.6 to 223.5 minutes (median 8.2; the longest is 18, 3087 pages), a scan 7.5 to 46.8
(median 23.3). Text-layer books with garbled pages cost like scans on those pages: Docling recognises them (111: 8.2
s per page).

A run's own report carries the same phases for its book in `seconds` of report.json, timed a little narrower: a
reading's time is the engine's own call, kept with the reading, so a run that takes readings from the cache still
reports what the book took to read, while the read job's lookup and the writing of the reading are left out. The
report's reading numbers can therefore sit slightly below this table's, most visibly on fast text-layer books. A
reading kept before readings were timed makes its engine's time unknown rather than zero (`readings_untimed`).
