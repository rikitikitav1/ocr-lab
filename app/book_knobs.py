# book-level knobs: what metadata and table-of-contents stages read before any run exists
from functools import cache

import job_specs
import settings
import yaml
from orm.catalogue import Book
from orm.db import Session

KNOBS = {
    "metadata.title_pages.head": "pages from the start read as title and copyright pages",
    "metadata.title_pages.tail": "pages from the end read as title and copyright pages",
    "structure.contents_pages": "book page ranges of the printed contents, [[first, last], ...], 1-based",
    "structure.skip_root_bookmark": "the only top bookmark is the book itself: its children become the top level",
    "structure.ignore_bookmarks": "the bookmarks are not the contents (one per page, image file names): "
                                  "leave them out",
    "structure.chapter_label": "the word chapters open with, a line of it and one more word at a page's top "
                               "(\"درس\" in \"درس اول\"); used when no contents source holds the book",
    "structure.from_headings": "when no contents source holds the book, read every page as a picture and take the "
                               "chapters from its headings grouped by look; false lets such a book fail at once",
    "structure.reading_level": "the engines read the nodes of this tree level (0 is the top), a node over 100 pages as "
                               "its own pages and its children; empty takes the automatic level",
}


@cache
def defaults() -> dict:
    conf = yaml.safe_load((settings.CONFIG_DIR / "metadata.yaml").read_text())
    return {"metadata.title_pages.head": int(conf["title_pages"]["head"]),
            "metadata.title_pages.tail": int(conf["title_pages"]["tail"]),
            "structure.contents_pages": None,
            "structure.skip_root_bookmark": False,
            "structure.ignore_bookmarks": False,
            "structure.chapter_label": None,
            "structure.from_headings": True,
            "structure.reading_level": None}


def check(knobs: dict | None, pages: int | None = None) -> dict:
    knobs = knobs or {}
    unknown = set(knobs) - set(KNOBS)
    if unknown:
        raise job_specs.Refused(f"unknown book knobs {sorted(unknown)}; known: {KNOBS}")
    for name in ("metadata.title_pages.head", "metadata.title_pages.tail"):
        if name in knobs and not (isinstance(knobs[name], int) and 0 <= knobs[name] <= 200):
            raise job_specs.Refused(f"{name} must be an integer from 0 to 200")
    for name in ("structure.skip_root_bookmark", "structure.ignore_bookmarks", "structure.from_headings"):
        if name in knobs and not isinstance(knobs[name], bool):
            raise job_specs.Refused(f"{name} must be true or false")
    level, deepest = knobs.get("structure.reading_level"), job_specs.MAX_READING_LEVEL
    if level is not None and not (isinstance(level, int) and not isinstance(level, bool) and 0 <= level <= deepest):
        raise job_specs.Refused(f"structure.reading_level must be an integer from 0 to {deepest}")
    label = knobs.get("structure.chapter_label")
    if label is not None and not (isinstance(label, str) and len(label.split()) == 1):
        raise job_specs.Refused("structure.chapter_label must be one word")
    ranges = knobs.get("structure.contents_pages")
    if ranges is not None:
        ok = isinstance(ranges, list) and all(
            isinstance(r, list) and len(r) == 2 and all(isinstance(x, int) for x in r) and 1 <= r[0] <= r[1]
            and (pages is None or r[1] <= pages) for r in ranges)
        if not ok:
            raise job_specs.Refused("structure.contents_pages must be [[first, last], ...] "
                                    f"within 1..{pages or 'pages'}")
    return knobs


def of(book_id: int) -> dict:
    with Session() as session:
        stored = session.get(Book, book_id).knobs or {}
    return {**defaults(), **stored}


def overrides(book_id: int) -> dict:
    with Session() as session:
        return dict(session.get(Book, book_id).knobs or {})
