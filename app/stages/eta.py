# how long a book's run takes and when it starts, from what the stand's finished runs cost per page
import statistics

import job_costs
from orm.catalogue import Book, Piece, Run, RunStatus
from orm.db import Session
from orm.jobs import Job
from sqlalchemy import func, select

# the newest finished runs looked at for the cost
LOOKED_AT = 60


def _scanned(book: Book) -> int:
    layer = book.text_layer or {}
    return len(layer.get("without_layer", [])) + len(layer.get("garbled", []))


# seconds per page of the newest runs whose engines really read, by kind of book: job time over the book's pages
def _costs(session) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {"text": [], "scan": []}
    done = select(Run).where(Run.status == RunStatus.DONE).order_by(Run.id.desc()).limit(LOOKED_AT)
    for run in session.scalars(done):
        jobs = session.execute(select(Job.type, Job.elapsed, Job.result).where(Job.run_id == run.id,
                                                                               Job.status == "done")).all()
        reads = [(e, (r or {}).get("kept")) for t, e, r in jobs if t == "read_piece"]
        book = session.get(Book, run.book_id)
        # a run with a kept reading tells nothing about what reading costs
        if not reads or any(job_costs.kept_read(e, kept) for e, kept in reads) or not book.pages:
            continue
        total = sum(e or 0 for t, e, _ in jobs if t in ("read_piece", "assemble_piece", "book_metrics"))
        out["scan" if _scanned(book) > book.pages / 2 else "text"].append(total / book.pages)
    return out


def _spread(found: list[float]) -> dict | None:
    if not found:
        return None
    return {"median": statistics.median(found), "min": min(found), "max": max(found), "runs": len(found)}


# pages read by recognition cost like a scan's, the rest like a text book's; unknown while a kind has no runs
def _seconds(book: Book, spreads: dict, key: str) -> float | None:
    scanned = _scanned(book)
    text = max((book.pages or 0) - scanned, 0)
    parts = [(text, spreads["text"]), (scanned, spreads["scan"])]
    if any(pages and spread is None for pages, spread in parts):
        return None
    return sum(pages * spread[key] for pages, spread in parts if pages)


# a run's own time as a spread, and when it starts: what other books' runs queued ahead still have to do
def estimate(book_id: int, run_id: int | None = None) -> dict:
    with Session() as session:
        book = session.get(Book, book_id)
        costs = _costs(session)
        spreads = {kind: _spread(found) for kind, found in costs.items()}
        own = {key: (round(v) if (v := _seconds(book, spreads, key)) is not None else None)
               for key in ("min", "median", "max")}
        ahead, unknown = 0.0, 0
        waiting = select(Run).where(Run.status.in_((RunStatus.QUEUED, RunStatus.RUNNING)), Run.book_id != book_id)
        for run in session.scalars(waiting.order_by(Run.id)):
            if run_id is not None and run.id >= run_id:
                continue
            counts = dict(session.execute(select(Piece.status, func.count()).where(Piece.run_id == run.id)
                                          .group_by(Piece.status)).all())
            left = 1 - counts.get("done", 0) / sum(counts.values()) if counts else 1
            cost = _seconds(session.get(Book, run.book_id), spreads, "median")
            if cost is None:
                unknown += 1
            else:
                ahead += cost * left
    return {"run_seconds": own, "starts_in_seconds": None if unknown else round(ahead),
            "cost_runs": {kind: len(found) for kind, found in costs.items()}}
