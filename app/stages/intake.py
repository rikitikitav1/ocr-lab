# what the book is made of: files, pages, text layer per page, bookmarks, printed contents pages
import re
import shutil
from pathlib import Path

import artifacts
import book_knobs
import pdf
import settings
from orm.catalogue import Book, BookFile
from orm.db import Session
from sqlalchemy import select

STAGE = "intake"
# a printed contents line: a title, a run of dots or spaces, a page number
DOT_LEADER = re.compile(r"^\s*\S.{2,}?(?:\.\s?){3,}\s*\d{1,4}\s*$", re.MULTILINE)
CONTENTS_SCAN_PAGES = 30
CONTENTS_MIN_LINES = 5


def file_store_path(sha: str) -> Path:
    return Path("files") / sha[:2] / f"{sha}.pdf"


def book_identity(file_shas: list[str]) -> str:
    return artifacts.input_hash(files=file_shas)


# copied once by content: the same file in two books is stored once
def store(source: Path, sha: str) -> Path:
    relative = file_store_path(sha)
    target = settings.DATA_DIR / relative
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")
        shutil.copyfile(source, tmp)
        tmp.replace(target)
    return relative


def register(sources: list[tuple[Path, str]], knobs: dict | None = None) -> tuple[int, bool]:
    shas = [artifacts.sha256_file(path) for path, _ in sources]
    identity = book_identity(shas)
    with Session() as session:
        known = session.scalar(select(Book.id).where(Book.sha256 == identity))
        if known is not None:
            return known, False
        book = Book(sha256=identity, stage="uploaded")
        session.add(book)
        session.flush()
        first = 1
        for ord, ((path, name), sha) in enumerate(zip(sources, shas, strict=True)):
            stored = store(path, sha)
            pages = pdf.page_count(settings.DATA_DIR / stored)
            session.add(BookFile(book_id=book.id, ord=ord, sha256=sha, file_path=str(stored), file_name=name,
                                 pages=pages, first_page=first))
            first += pages
        book.pages = first - 1
        book.knobs = book_knobs.check(knobs, book.pages)
        session.commit()
        return book.id, True


def files_of(book_id: int) -> list[BookFile]:
    with Session() as session:
        return list(session.scalars(select(BookFile).where(BookFile.book_id == book_id).order_by(BookFile.ord)))


def probe(book_id: int) -> dict:
    files = files_of(book_id)
    given = book_knobs.of(book_id)["toc.contents_pages"]
    key = artifacts.input_hash(stage=STAGE, files=[f.sha256 for f in files], layer_rule=pdf.LAYER_RULE,
                               contents_pages=given)
    owner = artifacts.Owner(book_id=book_id)
    done = artifacts.find_done(owner, STAGE, "probe.json", key)
    if done is not None:
        import json

        result = json.loads(artifacts.read(done))
    else:
        result = _probe(files)
        if given:
            result["has_printed_contents"] = True
            result["toc_sources"]["contents_pages_given"] = given
        artifacts.write(owner, artifacts.book_dir(book_id), STAGE, "probe.json", result, key)
    with Session() as session:
        book = session.get(Book, book_id)
        book.text_layer = result["text_layer"]
        book.has_bookmarks = result["has_bookmarks"]
        book.has_printed_contents = result["has_printed_contents"]
        book.toc_sources = result["toc_sources"]
        session.commit()
    return result


def _probe(files: list[BookFile]) -> dict:
    without_layer, garbled, bookmarks, contents_lines = [], [], 0, 0
    per_file = []
    for f in files:
        path = settings.DATA_DIR / f.file_path
        texts = pdf.page_texts(path)
        missing = [f.first_page + i for i, t in texts.items() if not pdf.has_layer(t)]
        without_layer += missing
        garbled += [f.first_page + i for i, t in texts.items() if pdf.garbled(t)]
        marks = pdf.outline(path)
        bookmarks += len(marks)
        head = "\n".join(texts[i] for i in sorted(texts)[:CONTENTS_SCAN_PAGES])
        lines = len(DOT_LEADER.findall(head))
        contents_lines += lines
        per_file.append({"ord": f.ord, "pages": f.pages, "pages_without_layer": len(missing),
                         "bookmarks": len(marks), "contents_lines": lines})
    total = sum(f.pages for f in files)
    return {
        "text_layer": {"pages": total, "without_layer": without_layer, "with_layer": total - len(without_layer),
                       "garbled": garbled},
        "has_bookmarks": bookmarks > 0,
        "has_printed_contents": contents_lines >= CONTENTS_MIN_LINES,
        "toc_sources": {"bookmarks": bookmarks, "printed_contents_lines": contents_lines},
        "files": per_file,
    }
