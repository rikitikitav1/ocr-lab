# chapter files: each file a chapter titled by its biggest words; a part title page also gives the part
from collections import Counter
from pathlib import Path

import numerals
from orm.catalogue import BookFile

from stages.structure.sources import Entry, SourceEntries, book_lines, conf

TITLE_MAX_CHARS = 120
LOOK_PAGES = 4
OPENING_SIZE = 18
HEAD_LINES = 4


def _words(lines: list) -> list:
    return [x for x in lines if 2 < len(x.text.strip()) <= TITLE_MAX_CHARS and any(c.isalpha() for c in x.text)]


def _lone_words(lines: list) -> set[str]:
    return {t.lower() for x in lines[:HEAD_LINES] if len(t := x.text.strip()) >= 3 and t.isalpha()}


# a word alone with its number on the next line ("CHAPTER", "2"), not a running head that also stands alone
def _numbered_words(lines: list) -> set[str]:
    head = [x.text.strip() for x in lines[:HEAD_LINES + 1]]
    return {t.lower() for t, n in zip(head, head[1:], strict=False)
            if len(t) >= 3 and t.isalpha() and numerals.value(n.rstrip(".")) is not None}


# the chapter label stands alone over its number in most files, the part label alone on two files' first pages
def _labels(openings: list[list[list]]) -> tuple[set[str], set[str]]:
    seen = Counter(w for pages in openings for w in set().union(*map(_numbered_words, pages)))
    chapter = {w for w, n in seen.most_common(1) if n >= conf()["scan_layer"]["headings"]["label_min"]}
    if not chapter:
        return chapter, set()
    # parts hold chapters, so a word on every file's first page is the series or the book's name, not a part
    firsts = Counter(w for pages in openings if pages for w in _lone_words(pages[0]))
    return chapter, {w for w, n in firsts.items() if 2 <= n < len(openings) and w not in chapter}


def _title(lines: list, skip: set[str]) -> str | None:
    words = [x for x in _words(lines) if x.text.strip().lower() not in skip]
    if not words:
        return None
    biggest = max(x.size for x in words)
    return " ".join(x.text.strip() for x in words if x.size == biggest)


def _part_page(lines: list, part: set[str]) -> str | None:
    texts = [x.text.strip() for x in lines]
    for i, text in enumerate(texts[:-1]):
        if text.lower() in part:
            return f"{text.title()} {texts[i + 1]}"
    return None


# the opening page is the first one with a bare chapter label or with words set big
def _opening(pages: list[list], chapter: set[str]) -> list:
    for lines in pages:
        if any(x.text.strip().lower() in chapter for x in lines):
            return lines
        if any(x.size >= OPENING_SIZE for x in _words(lines)):
            return lines
    return pages[0] if pages else []


def read(files: list[BookFile]) -> SourceEntries:
    out = SourceEntries("files")
    if len(files) < 2:
        out.failed = "one file"
        return out
    wanted = {f.first_page + i for f in files for i in range(min(LOOK_PAGES, f.pages))}
    lines = book_lines(files, wanted)
    chapters = []
    chapter_label, part_label = _labels([[lines.get(f.first_page + i, []) for i in range(min(LOOK_PAGES, f.pages))]
                                         for f in files])
    for f in files:
        first = lines.get(f.first_page, [])
        part = _part_page(first, part_label)
        start = f.first_page + 1 if part else f.first_page
        if part:
            out.entries.append(Entry(part, 1, f.first_page, evidence=f"part title page of file {f.ord}", verified=True))
        pages = [lines.get(p, []) for p in range(start, f.first_page + min(LOOK_PAGES, f.pages))]
        title = _title(_opening(pages, chapter_label), chapter_label) or Path(f.file_name).stem
        chapters.append(Entry(title, 1, start, evidence=f"file {f.ord} {f.file_name}", verified=True))
        out.entries.append(chapters[-1])
    if len(chapters) < len(out.entries):
        for e in chapters:
            e.level = 2
    return out
