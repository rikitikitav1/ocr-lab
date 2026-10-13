import re
from pathlib import Path

import book_knobs
import job_queue
import job_specs
import numerals
import settings
from job_signals import Deferred
from mcp_tools import tool
from orm.catalogue import Book, BookFile, MetadataField, MetadataVersion, Run, TocVersion
from orm.db import Session
from orm.jobs import Job
from sqlalchemy import select
from stages import eta, file_order, intake, versions
from stages.metadata import fields, resolve
from stages.metadata.candidates import REQUIRED, SOUGHT
from stages.toc import collect, evidence


def _allowed(path: Path) -> Path:
    resolved = path.resolve()
    roots = (settings.SHELF_DIR.resolve(), (settings.DATA_DIR / "inbox").resolve())
    if not any(resolved.is_relative_to(r) for r in roots):
        raise job_specs.Refused(f"{path} is outside the shelf and data/inbox")
    if not resolved.is_file():
        raise LookupError(f"no file {path}")
    return resolved


ORDERS = ("given", "by_number")


# the order of the files makes the book, so it is settled before the book is registered
def submit(sources: list[tuple[Path, str]], knobs: dict | None = None, then: list[str] | None = None,
           order: str = "given") -> dict:
    if not sources:
        raise job_specs.Refused("a submission needs at least one PDF file")
    if order not in ORDERS:
        raise job_specs.Refused(f"order must be one of {ORDERS}")
    book_knobs.check(knobs)
    if order == "by_number":
        sources, _ = file_order.by_number(sources)
    options = job_specs.check("intake", {"book_id": 0, **({"then": then} if then is not None else {})})
    book_id, created = intake.register(sources, knobs)
    job_id = None
    if created:
        job_id = job_queue.enqueue("intake", {**options, "book_id": book_id}, book_id=book_id)
    elif knobs:
        set_book_knobs(book_id, set=knobs)
    # the intake job's id: waiting on it waits for the whole chain the submission asked for
    return {**get_book(book_id), "created": created, "job_id": job_id}


@tool("add_book", "POST /v1/books",
      "Registers a book from PDF files on the shelf (shelf_paths, under books/) or in data/inbox (file_paths), "
      "ordered as given or by_number, and queues its intake job (cpu lane), which chains metadata and toc "
      "unless `then` says otherwise. Returns the book view with `created`; a known file set returns the "
      "existing book.")
def add_book(shelf_paths: list[str] | None = None, file_paths: list[str] | None = None,
             knobs: dict | None = None, then: list[str] | None = None, order: str = "given") -> dict:
    paths = [_allowed(settings.SHELF_DIR / "books" / p) for p in shelf_paths or []]
    paths += [_allowed(Path(p)) for p in file_paths or []]
    return submit([(p, p.name) for p in paths], knobs, then, order)


# a knob change takes effect at the next collection of metadata or the table of contents
@tool("set_book_knobs", "PATCH /v1/books/{id}/knobs",
      "Sets or unsets a book's own knobs (see `knobs`, group book) and returns its overrides and effective "
      "values; they take effect at the next metadata or toc collection.")
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
    version = versions.current(session, MetadataVersion, book_id)
    if version is None:
        return {}
    found = fields.of_version(session, version.id)
    return {"version": version.version, "fields": found,
            "missing": sorted(n for n, f in found.items() if f["value"] is None and n in REQUIRED),
            "not_found": sorted(n for n, f in found.items() if f["value"] is None and n in SOUGHT)}


# the current toc version and the source its base came from; toc_sources are intake's counts per source
def _toc(session, book_id: int) -> dict | None:
    version = versions.current(session, TocVersion, book_id)
    return {"version": version.version, "base": evidence.base(session, version.id)} if version else None


def _view(session, book: Book) -> dict:
    files = session.scalars(select(BookFile).where(BookFile.book_id == book.id).order_by(BookFile.ord)).all()
    runs = session.scalars(select(Run).where(Run.book_id == book.id).order_by(Run.id)).all()
    layer = book.text_layer or {}
    # a file's path is its stored copy under the data dir (data/ on the host, /data in the containers)
    return {
        "id": book.id, "sha256": book.sha256, "pages": book.pages, "stage": book.stage,
        "files": [{"ord": f.ord, "name": f.file_name, "path": f.file_path, "pages": f.pages,
                   "first_page": f.first_page} for f in files],
        "text_layer": {"with_layer": layer.get("with_layer"), "without_layer": len(layer.get("without_layer", [])),
                       "garbled": len(layer.get("garbled", [])),
                       "pages_without_layer": layer.get("without_layer", [])[:200]} if layer else None,
        "has_bookmarks": book.has_bookmarks, "has_printed_contents": book.has_printed_contents,
        "toc_sources": book.toc_sources, "toc": _toc(session, book.id), "metadata": _fields(session, book.id),
        "knobs": book.knobs or {}, "page_offset": book.page_offset,
        "result_run_id": book.result_run_id,
        "runs": [{"id": r.id, "status": r.status} for r in runs],
        "stages": _stages(session, book.id),
    }


# the newest job of each book-level stage, with its error when it failed, so a stuck book says where
def _stages(session, book_id: int) -> dict:
    out: dict = {}
    for job in session.scalars(select(Job).where(Job.book_id == book_id, Job.run_id.is_(None)).order_by(Job.id)):
        out[job.type] = {"job": job.id, "status": job.status,
                         "error": (job.error or {}).get("error") if job.status == "error" else None}
    return out


@tool("book", "GET /v1/books/{id}",
      "One book: files, text layer, toc sources, current metadata, knobs, runs, the result run, the newest job "
      "of each book stage with its error, and whether metadata and toc are stale.")
def get_book(id: int) -> dict:
    with Session() as session:
        book = session.get(Book, id)
        if book is None:
            raise LookupError(f"no book {id}")
        view = _view(session, book)
    return {**view, "stale": _stale(id), "eta": eta.estimate(id)}


# whether the current versions were made from other inputs than today's; a run collects stale ones again first
def _stale(book_id: int) -> dict:
    out = {}
    for what, check in (("metadata", resolve.stale), ("toc", collect.stale)):
        try:
            out[what] = check(book_id)
        except Deferred as e:
            out[what] = f"unknown: {e}"
    return out


# volumes go by number, Roman ones included; a volume that is no number goes after them by its text
def volume_order(value) -> tuple:
    text = str(value or "").strip()
    first = text.split()[0].rstrip(".") if text else ""
    number = numerals.value(first) or (int(m.group()) if (m := re.match(r"\d+", first)) else None)
    return (0, number, text) if number else (1, 0, text.lower())


LISTED_FIELDS = ("title", "languages", "series", "volume")


# the current metadata values the list filters and shows, for all books in one query
def _listed_values(session) -> dict[int, dict]:
    rows = session.execute(select(MetadataVersion.book_id, MetadataField.name, MetadataField.value)
                           .join(MetadataField, MetadataField.metadata_version_id == MetadataVersion.id)
                           .where(MetadataVersion.current, MetadataField.name.in_(LISTED_FIELDS)))
    out: dict[int, dict] = {}
    for book_id, name, value in rows:
        out.setdefault(book_id, {})[name] = value
    return out


def _last_runs(session, book_ids: list[int]) -> dict[int, dict]:
    runs = session.scalars(select(Run).where(Run.book_id.in_(book_ids)).order_by(Run.id))
    return {r.book_id: {"id": r.id, "status": r.status} for r in runs}


# brief rows by default: the full view of every book on the shelf is too much to read at once
@tool("books", "GET /v1/books",
      "Lists books as brief rows (id, title, stage, pages, languages, result run, last run) by default, or the full"
      " `book` view with brief=false; filtered by stage, a title substring `q` or a series (then sorted by volume).")
def list_books(stage: str | None = None, q: str | None = None, series: str | None = None,
               limit: int = 100, offset: int = 0, brief: bool = True) -> list[dict]:
    with Session() as session:
        query = select(Book).order_by(Book.id)
        if stage:
            query = query.where(Book.stage == stage)
        books = list(session.scalars(query))
        values = _listed_values(session)
        def value(book, name):
            return values.get(book.id, {}).get(name)
        if q:
            books = [b for b in books if q.lower() in str(value(b, "title") or "").lower()]
        if series:
            books = [b for b in books if str(value(b, "series") or "").lower() == series.lower()]
            books.sort(key=lambda b: (volume_order(value(b, "volume")), b.id))
        books = books[offset:offset + limit]
        if not brief:
            return [_view(session, b) for b in books]
        last = _last_runs(session, [b.id for b in books])
        return [{"id": b.id, "title": value(b, "title"), "stage": b.stage, "pages": b.pages,
                 "languages": value(b, "languages"), "result_run_id": b.result_run_id, "last_run": last.get(b.id)}
                for b in books]


def _checked_what(what: list[str] | None) -> list[str]:
    what = what or job_specs.RECOLLECT_DEFAULT
    unknown = [w for w in what if w not in job_specs.BOOK_STAGES]
    if unknown:
        raise job_specs.Refused(f"unknown stages {unknown}; known: {list(job_specs.BOOK_STAGES)}")
    missing = [w for w in what if w not in job_specs.BUILT_BOOK_STAGES]
    if missing:
        raise job_specs.Refused(f"stages {missing} are not built yet; built: {list(job_specs.BUILT_BOOK_STAGES)}")
    return what


def _checked_run(what: list[str], run: bool) -> None:
    collects_toc = "toc" in what or what == ["intake"]
    if run and not collects_toc:
        raise job_specs.Refused("run starts once the toc is collected; add toc to what")


def _enqueue_recollect(session, book_id: int, what: list[str], run: bool = False) -> int:
    # intake again re-reads the files, then chains the stages asked for, or both as on submission
    if "intake" in what:
        then = [w for w in what if w != "intake"] or ["metadata", "toc"]
        return job_queue.enqueue("intake", {"book_id": book_id, "then": then + ["run"] * run, "force": True},
                                 book_id=book_id, session=session)
    if "metadata" not in what:
        return job_queue.enqueue("toc", {"book_id": book_id, "what": ["toc"], "force": True, "run": run},
                                 book_id=book_id, session=session)
    return job_queue.enqueue("metadata", {"book_id": book_id, "what": what, "force": True, "run": run},
                             book_id=book_id, session=session)


@tool("recollect", "POST /v1/books/{id}/recollect",
      "Queues one job that collects a book's stages again (`what` from intake, metadata, toc; default "
      "metadata), forced even when nothing is stale; `run` starts a run once the toc is collected. Returns {job_id}; "
      "follow it with wait_job.")
def recollect(id: int, what: list[str] | None = None, run: bool = False) -> dict:
    what = _checked_what(what)
    _checked_run(what, run)
    with Session() as session:
        if session.get(Book, id) is None:
            raise LookupError(f"no book {id}")
        job_id = _enqueue_recollect(session, id, what, run)
        session.commit()
    return {"job_id": job_id}


# one all-or-nothing call for many books: every id and stage is checked before a job is queued
@tool("recollect_books", "POST /v1/books/recollect",
      "Like recollect for many books at once (all books when `ids` is empty); every id and stage is checked "
      "before any job is queued. `run` starts a run for every book once its toc is collected, so with empty `ids` "
      "it runs the whole shelf on the GPU. Returns {jobs: {book_id: job_id}}.")
def recollect_books(ids: list[int] | None = None, what: list[str] | None = None, run: bool = False) -> dict:
    what = _checked_what(what)
    _checked_run(what, run)
    with Session() as session:
        known = set(session.scalars(select(Book.id)))
        ids = ids or sorted(known)
        unknown = [i for i in ids if i not in known]
        if unknown:
            raise LookupError(f"no books {unknown}")
        jobs = {book_id: _enqueue_recollect(session, book_id, what, run) for book_id in ids}
        session.commit()
    return {"jobs": jobs}
