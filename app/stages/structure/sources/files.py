# chapter files: each file a chapter titled by its biggest words; a part title page also gives the part
from pathlib import Path

from orm.catalogue import BookFile

from stages.structure.sources import Entry, SourceEntries, book_lines, conf

TITLE_MAX_CHARS = 120
LOOK_PAGES = 4
OPENING_SIZE = 18


def _words(lines: list) -> list:
    return [x for x in lines if 2 < len(x.text.strip()) <= TITLE_MAX_CHARS and any(c.isalpha() for c in x.text)]


def _labels(kind: str) -> set[str]:
    return {w.lower() for w in conf()["text_layer"]["numbering"][kind]}


def _title(lines: list, skip: set[str]) -> str | None:
    words = [x for x in _words(lines) if x.text.strip().lower() not in skip]
    if not words:
        return None
    biggest = max(x.size for x in words)
    return " ".join(x.text.strip() for x in words if x.size == biggest)


def _part_page(lines: list) -> str | None:
    texts = [x.text.strip() for x in lines]
    for i, text in enumerate(texts[:-1]):
        if text.lower() in _labels("part"):
            return f"{text.title()} {texts[i + 1]}"
    return None


# the opening page is the first one with a bare chapter label or with words set big
def _opening(pages: list[list]) -> list:
    for lines in pages:
        if any(x.text.strip().lower() in _labels("chapter") for x in lines):
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
    for f in files:
        first = lines.get(f.first_page, [])
        part = _part_page(first)
        start = f.first_page + 1 if part else f.first_page
        if part:
            out.entries.append(Entry(part, 1, f.first_page, evidence=f"part title page of file {f.ord}", verified=True))
        pages = [lines.get(p, []) for p in range(start, f.first_page + min(LOOK_PAGES, f.pages))]
        title = _title(_opening(pages), _labels("chapter")) or Path(f.file_name).stem
        chapters.append(Entry(title, 1, start, evidence=f"file {f.ord} {f.file_name}", verified=True))
        out.entries.append(chapters[-1])
    if len(chapters) < len(out.entries):
        for e in chapters:
            e.level = 2
    return out
