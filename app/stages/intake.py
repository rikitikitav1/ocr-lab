# what the book is made of: files, pages, text layer per page, bookmarks, printed contents pages
import shutil
from pathlib import Path

import artifacts
import book_knobs
import code_version
import pdf
import settings
from orm.catalogue import Book, BookFile
from orm.db import Session
from sqlalchemy import select

from stages.toc.sources import printed_contents

STAGE = "intake"


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


# a book's files stay stored by content; its folder links each by order and name, so a person finds them there
def link_sources(book_id: int) -> None:
    folder = settings.DATA_DIR / artifacts.book_dir(book_id) / "source"
    folder.mkdir(parents=True, exist_ok=True)
    for f in files_of(book_id):
        name = Path(f.file_name).name
        # a file name is at most 255 bytes; a long title is cut, keeping its extension
        stem, suffix = Path(name).stem, Path(name).suffix
        while len(f"{f.ord}-{stem}{suffix}".encode()) > 255:
            stem = stem[:-1]
        link = folder / f"{f.ord}-{stem}{suffix}"
        if not link.exists() and not link.is_symlink():
            link.symlink_to(Path("../../..") / f.file_path)


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
        book_id = book.id
    link_sources(book_id)
    return book_id, True


def files_of(book_id: int) -> list[BookFile]:
    with Session() as session:
        return list(session.scalars(select(BookFile).where(BookFile.book_id == book_id).order_by(BookFile.ord)))


def code_hash() -> str:
    sources = settings.APP_DIR / "stages" / "toc" / "sources"
    own = [settings.APP_DIR / "stages" / "intake.py", sources / "__init__.py", sources / "printed_contents.py",
           sources / "numbering.py"]
    return code_version.files_hash(own, ("toc.yaml",)).hexdigest()[:16]


def probe(book_id: int) -> dict:
    link_sources(book_id)
    files = files_of(book_id)
    given = book_knobs.of(book_id)["toc.contents_pages"]
    inputs = artifacts.Inputs({"stage": STAGE, "files": [f.sha256 for f in files], "layer_rule": pdf.LAYER_RULE,
                               "knobs": {"toc.contents_pages": given}, "code": code_hash()})
    owner = artifacts.Owner(book_id=book_id)
    done = artifacts.find_done(owner, STAGE, "probe.json", inputs.key)
    if done is not None:
        import json

        result = json.loads(artifacts.read(done))
    else:
        result = _probe(files)
        if given:
            result["has_printed_contents"] = True
            result["toc_sources"]["contents_pages_given"] = given
        artifacts.write(owner, artifacts.book_dir(book_id), STAGE, "probe.json", result, inputs)
    with Session() as session:
        book = session.get(Book, book_id)
        book.text_layer = result["text_layer"]
        book.has_bookmarks = result["has_bookmarks"]
        book.has_printed_contents = result["has_printed_contents"]
        book.toc_sources = result["toc_sources"]
        session.commit()
    return result


# a book page as (file ord, page in that file), so a page named in a report can be opened in its own file
def located(files: list[BookFile], pages: list[int]) -> dict[int, list[int]]:
    out = {}
    for page in sorted(set(pages)):
        f = next((f for f in files if f.first_page <= page < f.first_page + f.pages), None)
        if f is not None:
            out[page] = [f.ord, page - f.first_page + 1]
    return out


def _probe(files: list[BookFile]) -> dict:
    without_layer, garbled, bookmarks = [], [], 0
    per_file = []
    for f in files:
        path = settings.DATA_DIR / f.file_path
        texts = pdf.page_texts(path)
        missing = [f.first_page + i for i, t in texts.items() if not pdf.has_layer(t)]
        without_layer += missing
        garbled += [f.first_page + i for i, t in texts.items() if pdf.garbled(t)]
        marks = pdf.outline(path)
        bookmarks += len(marks)
        per_file.append({"ord": f.ord, "pages": f.pages, "pages_without_layer": len(missing),
                         "bookmarks": len(marks)})
    total = sum(f.pages for f in files)
    # the toc stage's own finder, so the catalogue and the toc never disagree on whether contents exist
    contents_pages, _ = printed_contents.find_pages(files, None)
    return {
        "text_layer": {"pages": total, "without_layer": without_layer, "with_layer": total - len(without_layer),
                       "garbled": garbled},
        "where": located(files, [*without_layer, *garbled, *contents_pages]),
        "has_bookmarks": bookmarks > 0,
        "has_printed_contents": bool(contents_pages),
        "toc_sources": {"bookmarks": bookmarks, "printed_contents_pages": contents_pages},
        "files": per_file,
    }
