# the only two ways artifacts leave the stand: a run deleted by name, and the cleanup of heavy intermediates
import shutil
from datetime import UTC, datetime

import job_queue
import job_specs
import settings
from orm.catalogue import Artifact, Book, Run
from orm.db import Session
from sqlalchemy import func, select

from stages import result_run, run_state


# a run is in use while its state says so or any of its jobs still lives
def _in_use(run: Run) -> bool:
    return run_state.busy(run) or bool(job_queue.live_ids(run_id=run.id))


def delete_run(id: int) -> dict:
    with Session() as session:
        # the run's row is held to the commit, so a resume waits instead of queuing jobs under a run going away
        run = session.scalar(select(Run).where(Run.id == id).with_for_update())
        if run is None:
            raise LookupError(f"no run {id}")
        if _in_use(run):
            raise job_specs.Busy(id)
        book_id, bundle_dir = run.book_id, run.bundle_dir
        was_result = session.get(Book, book_id).result_run_id == id
        files = session.scalar(select(func.count()).select_from(Artifact).where(Artifact.run_id == id))
        session.delete(run)
        session.commit()
    for folder in {settings.DATA_DIR / "runs" / str(book_id) / str(id),
                   *([settings.DATA_DIR / bundle_dir] if bundle_dir else [])}:
        shutil.rmtree(folder, ignore_errors=True)
    result = result_run.recompute(book_id) if was_result else None
    return {"deleted": id, "artifacts": files, "was_result": was_result, "result_run_id": result}


# heavy intermediates of runs that are not their book's result; book-level readings are the cache every run reads
def _removable(session, hold: bool = False) -> list[Artifact]:
    results = select(Book.result_run_id).where(Book.result_run_id.is_not(None))
    rows = list(session.scalars(select(Artifact).where(Artifact.heavy, Artifact.run_id.is_not(None),
                                                       Artifact.removed_at.is_(None), Artifact.run_id.not_in(results))
                                .order_by(Artifact.id)))
    # held, the runs' rows keep a resume from writing new dumps under the paths about to be removed
    runs = select(Run).where(Run.id.in_({a.run_id for a in rows}))
    busy = {r.id for r in session.scalars(runs.with_for_update() if hold else runs) if _in_use(r)}
    return [a for a in rows if a.run_id not in busy]


def cleanup(dry_run: bool = True) -> dict:
    with Session() as session:
        rows = _removable(session, hold=not dry_run)
        sizes = {a.id: (settings.DATA_DIR / a.path).stat().st_size if (settings.DATA_DIR / a.path).exists() else 0
                 for a in rows}
        out = {"dry_run": dry_run, "files": len(rows), "bytes": sum(sizes.values()),
               "runs": sorted({a.run_id for a in rows})}
        if not dry_run:
            now = datetime.now(UTC)
            for a in rows:
                (settings.DATA_DIR / a.path).unlink(missing_ok=True)
                a.removed_at = now
            session.commit()
    return out
