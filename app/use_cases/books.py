from pathlib import Path

import book_knobs
import job_queue
import job_specs
import settings
from mcp_tools import tool
from orm.catalogue import Book, BookFile, MetadataField, MetadataVersion, Run
from orm.db import Session
from sqlalchemy import select
from stages import intake
from stages.metadata.candidates import REQUIRED, SOUGHT


def _allowed(path: Path) -> Path:
    resolved = path.resolve()
    roots = (settings.SHELF_DIR.resolve(), (settings.DATA_DIR / "inbox").resolve())
    if not any(resolved.is_relative_to(r) for r in roots):
        raise job_specs.Refused(f"{path} is outside the shelf and data/inbox")
    if not resolved.is_file():
        raise LookupError(f"no file {path}")
    return resolved


def submit(sources: list[tuple[Path, str]], knobs: dict | None = None) -> dict:
    if not sources:
        raise job_specs.Refused("a submission needs at least one PDF file")
    book_knobs.check(knobs)
    book_id, created = intake.register(sources, knobs)
    if created:
        job_queue.enqueue("intake", {"book_id": book_id}, book_id=book_id)
    elif knobs:
        set_book_knobs(book_id, set=knobs)
    return {**get_book(book_id), "created": created}


@tool("add_book", "POST /v1/books")
def add_book(shelf_paths: list[str] | None = None, file_paths: list[str] | None = None,
             knobs: dict | None = None) -> dict:
    paths = [_allowed(settings.SHELF_DIR / "books" / p) for p in shelf_paths or []]
    paths += [_allowed(Path(p)) for p in file_paths or []]
    return submit([(p, p.name) for p in paths], knobs)


# a knob change takes effect at the next collection of metadata or the table of contents
@tool("set_book_knobs", "PATCH /v1/books/{id}/knobs")
def set_book_knobs(id: int, set: dict | None = None, unset: list[str] | None = None) -> dict:
    with Session() as session:
        book = session.get(Book, id)
        if book is None:
            raise LookupError(f"no book {id}")
        merged = {k: v for k, v in {**(book.knobs or {}), **(set or {})}.items() if k not in (unset or [])}
        book.knobs = book_knobs.check(merged, book.pages)
        session.commit()
    return {"knobs": book_knobs.overrides(id), "effective": book_knobs.of(id)}


def _fields(session, book_id: int) -> dict:
    version = session.scalar(select(MetadataVersion).where(MetadataVersion.book_id == book_id,
                                                           MetadataVersion.current))
    if version is None:
        return {}
    rows = session.scalars(select(MetadataField).where(MetadataField.metadata_version_id == version.id)).all()
    return {"version": version.version,
            "fields": {f.name: {"value": f.value, "source": f.source, "confidence": f.confidence} for f in rows},
            "missing": sorted(f.name for f in rows if f.value is None and f.name in REQUIRED),
            "not_found": sorted(f.name for f in rows if f.value is None and f.name in SOUGHT)}


def _view(session, book: Book) -> dict:
    files = session.scalars(select(BookFile).where(BookFile.book_id == book.id).order_by(BookFile.ord)).all()
    runs = session.scalars(select(Run).where(Run.book_id == book.id).order_by(Run.id)).all()
    layer = book.text_layer or {}
    return {
        "id": book.id, "sha256": book.sha256, "pages": book.pages, "stage": book.stage,
        "files": [{"ord": f.ord, "name": f.file_name, "pages": f.pages, "first_page": f.first_page} for f in files],
        "text_layer": {"with_layer": layer.get("with_layer"), "without_layer": len(layer.get("without_layer", [])),
                       "garbled": len(layer.get("garbled", [])),
                       "pages_without_layer": layer.get("without_layer", [])[:200]} if layer else None,
        "has_bookmarks": book.has_bookmarks, "has_printed_contents": book.has_printed_contents,
        "toc_sources": book.toc_sources, "metadata": _fields(session, book.id),
        "knobs": book.knobs or {},
        "result_run_id": book.result_run_id,
        "runs": [{"id": r.id, "status": r.status, "verdict": r.verdict} for r in runs],
    }


@tool("book", "GET /v1/books/{id}")
def get_book(id: int) -> dict:
    with Session() as session:
        book = session.get(Book, id)
        if book is None:
            raise LookupError(f"no book {id}")
        return _view(session, book)


@tool("books", "GET /v1/books")
def list_books(stage: str | None = None, verdict: str | None = None, q: str | None = None,
               series: str | None = None, limit: int = 100) -> list[dict]:
    with Session() as session:
        query = select(Book).order_by(Book.id)
        if stage:
            query = query.where(Book.stage == stage)
        if verdict:
            query = query.join(Run, Run.id == Book.result_run_id).where(Run.verdict == verdict)
        books = [_view(session, b) for b in session.scalars(query)]
    def value(book, name):
        return ((book["metadata"].get("fields") or {}).get(name) or {}).get("value")
    if q:
        books = [b for b in books if q.lower() in str(value(b, "title") or "").lower()]
    if series:
        books = [b for b in books if str(value(b, "series") or "").lower() == series.lower()]
        books.sort(key=lambda b: (str(value(b, "volume") or "").zfill(4), b["id"]))
    return books[:limit]


def _checked_what(what: list[str] | None) -> list[str]:
    what = what or job_specs.RECOLLECT_DEFAULT
    unknown = [w for w in what if w not in job_specs.BOOK_STAGES]
    if unknown:
        raise job_specs.Refused(f"unknown stages {unknown}; known: {list(job_specs.BOOK_STAGES)}")
    missing = [w for w in what if w not in job_specs.BUILT_BOOK_STAGES]
    if missing:
        raise job_specs.Refused(f"stages {missing} are not built yet; built: {list(job_specs.BUILT_BOOK_STAGES)}")
    return what


def _enqueue_recollect(session, book_id: int, what: list[str]) -> int:
    # intake again re-reads the files, then chains metadata as on submission
    if "intake" in what:
        return job_queue.enqueue("intake", {"book_id": book_id}, book_id=book_id, session=session)
    return job_queue.enqueue("metadata", {"book_id": book_id, "what": what, "force": True}, book_id=book_id,
                             session=session)


@tool("recollect", "POST /v1/books/{id}/recollect")
def recollect(id: int, what: list[str] | None = None) -> dict:
    what = _checked_what(what)
    with Session() as session:
        if session.get(Book, id) is None:
            raise LookupError(f"no book {id}")
        job_id = _enqueue_recollect(session, id, what)
        session.commit()
    return {"job_id": job_id}


# one call for many books, so a pass over the catalogue is not a loop of single calls
# all or nothing: every id and stage is checked before any job is queued, in one transaction
@tool("recollect_books", "POST /v1/books/recollect")
def recollect_books(ids: list[int] | None = None, what: list[str] | None = None) -> dict:
    what = _checked_what(what)
    with Session() as session:
        known = set(session.scalars(select(Book.id)))
        ids = ids or sorted(known)
        unknown = [i for i in ids if i not in known]
        if unknown:
            raise LookupError(f"no books {unknown}")
        jobs = {book_id: _enqueue_recollect(session, book_id, what) for book_id in ids}
        session.commit()
    return {"jobs": jobs}
