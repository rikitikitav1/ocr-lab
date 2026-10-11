# the book's result is its best finished run by the report's numbers, recomputed whenever a run finishes
import json

import artifacts
from orm.catalogue import Artifact, Book, Run, RunStatus, TocVersion
from orm.db import Session
from sqlalchemy import select

from stages import versions


# least text lost, then the largest share of toc sections found, then fewest paragraphs met twice, then least text added
def rank(run_id: int, numbers: dict) -> tuple:
    lost, extra = numbers.get("lost_text"), numbers.get("extra_text")
    subs = numbers.get("subs") or 0
    found = (numbers.get("subs_found") or 0) / subs if subs else 1.0
    return (1.0 if lost is None else lost, -found, numbers.get("duplicates") or 0, 1.0 if extra is None else extra,
            -run_id)


def _numbers(session, run_id: int) -> dict | None:
    row = session.scalar(select(Artifact).where(Artifact.run_id == run_id, Artifact.name == "report.json",
                                                Artifact.removed_at.is_(None)).order_by(Artifact.id.desc()))
    return json.loads(artifacts.read(row)).get("numbers") if row is not None else None


# only a run on the book's current toc can be its result: chapters come from it, metadata only names the languages
def recompute(book_id: int) -> int | None:
    with Session() as session:
        current = versions.current(session, TocVersion, book_id)
        toc = current.id if current is not None else None
        runs = session.scalars(select(Run.id).where(Run.book_id == book_id, Run.status == RunStatus.DONE,
                                                    Run.toc_version_id == toc))
        rated = [(rank(run_id, numbers), run_id) for run_id in runs if (numbers := _numbers(session, run_id))]
        best = min(rated)[1] if rated else None
        session.get(Book, book_id).result_run_id = best
        session.commit()
    return best
