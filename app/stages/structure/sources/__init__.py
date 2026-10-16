# what every table-of-contents source returns: entries in book order, pages numbered across files
from dataclasses import dataclass, field
from functools import cache

import pdf
import settings
import yaml
from orm.catalogue import BookFile

# printed page numbers run ahead of the PDF's pages by the front matter's count at most
PRINTED_AHEAD = 40


# the pages searched for a printed contents: the start of the book, then its end without the start's pages
def windows(total: int) -> tuple[list[int], list[int]]:
    c = conf()["contents"]
    head = list(range(1, min(total, c["scan_head"]) + 1))
    return head, [p for p in range(max(1, total - c["scan_tail"] + 1), total + 1) if p not in head]


# the book page ranges a knob gives, [[first, last], ...], as the pages they hold
def pages_of(ranges: list[list[int]]) -> list[int]:
    return sorted({p for a, b in ranges for p in range(a, b + 1)})


@dataclass
class Entry:
    title: str
    level: int | None
    page: int | None = None
    printed: str | None = None
    evidence: str = ""
    # the page was seen holding the title (an outline, a file start, a title found in the text)
    verified: bool = False
    source: str = ""
    votes: dict = field(default_factory=dict)


@dataclass
class SourceEntries:
    source: str
    entries: list[Entry] = field(default_factory=list)
    failed: str | None = None
    notes: dict = field(default_factory=dict)


@cache
def conf() -> dict:
    return yaml.safe_load((settings.CONFIG_DIR / "structure.yaml").read_text())


def book_lines(files: list[BookFile], pages: set[int] | None = None) -> dict[int, list[pdf.Line]]:
    out = {}
    for f in files:
        inside = range(f.first_page, f.first_page + f.pages)
        wanted = None if pages is None else [p - f.first_page for p in pages if p in inside]
        if wanted == []:
            continue
        for index, lines in pdf.page_lines(settings.DATA_DIR / f.file_path, wanted).items():
            out[f.first_page + index] = lines
    return out
