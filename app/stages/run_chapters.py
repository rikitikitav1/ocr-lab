# a run's chapters as its toc version gives them, with the pages cut from the bundle
from job_signals import Final
from orm.catalogue import Run, TocEntry
from sqlalchemy import select

from stages import assemble


def rows(session, toc_version_id: int) -> list[dict]:
    entries = session.scalars(select(TocEntry).where(TocEntry.toc_version_id == toc_version_id)
                              .order_by(TocEntry.ord))
    return [{"id": e.id, "ord": e.ord, "title": e.title, "level": e.level, "first_page": e.first_page,
             "last_page": e.last_page, "kind": e.kind} for e in entries]


def cut(session, run: Run) -> dict[str, frozenset[int]]:
    return assemble.cut_pages(run.toc_version_id, rows(session, run.toc_version_id))


def all_cut(session, run: Run) -> frozenset[int]:
    return frozenset().union(*cut(session, run).values())


def chapters(session, run: Run) -> list[dict]:
    return assemble.chapters_of(rows(session, run.toc_version_id), all_cut(session, run))


def chapter_entry(session, run: Run, ord: int) -> dict:
    found = next((c for c in chapters(session, run) if c["ord"] == ord), None)
    if found is None:
        raise Final(f"run {run.id} has no chapter {ord}")
    return found
