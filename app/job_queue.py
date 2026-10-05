import json
import time
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import job_specs
import psycopg
import settings
from orm.catalogue import Run
from orm.db import Session
from orm.jobs import Job
from sqlalchemy import func, select, text, update
from sqlalchemy.engine import make_url

ACTIVE = ("new", "paused", "running")
FINISHED = ("done", "error", "cancelled")
CHANNEL = "job_changed"
# a job the worker died under this many times would kill it again on every claim
MAX_RECLAIMS = 5

# the job running in this context: what its handler enqueues names it as the parent
running_job: ContextVar[int | None] = ContextVar("running_job", default=None)


@dataclass
class ClaimedJob:
    id: int
    type: str
    options: dict
    attempts: int
    deferred_seconds: int
    run_id: int | None
    book_id: int | None


def enqueue(type: str, options: dict | None = None, parent_id: int | None = None, run_id: int | None = None,
            book_id: int | None = None, session=None) -> int:
    job = Job(type=type, lane=job_specs.lane(type), options=job_specs.check(type, options),
              parent_id=parent_id if parent_id is not None else running_job.get(), run_id=run_id, book_id=book_id)
    if session is not None:
        session.add(job)
        session.flush()
        _notify(session, job)
        return job.id
    with Session() as own:
        own.add(job)
        own.flush()
        _notify(own, job)
        own.commit()
        return job.id


def claim_next(lane: str, code_hash: str | None = None) -> ClaimedJob | None:
    with Session() as session:
        job = session.scalars(
            select(Job)
            .where(Job.status == "new", Job.lane == lane, Job.apply_since <= func.now())
            .order_by(Job.apply_since, Job.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        ).first()
        if job is None:
            return None
        job.status = "running"
        job.code_hash = code_hash
        _notify(session, job)
        claimed = ClaimedJob(job.id, job.type, dict(job.options), job.attempts, job.deferred_seconds, job.run_id,
                             job.book_id)
        session.commit()
        return claimed


# single worker by design: anything still running belongs to a process that died
def requeue_stale(lanes: list[str]) -> list[int]:
    requeued = []
    with Session() as session:
        for job in session.scalars(select(Job).where(Job.status == "running", Job.lane.in_(lanes))):
            job.reclaims += 1
            if job.reclaims > MAX_RECLAIMS:
                job.status = "error"
                job.error = {"error": f"the worker stopped under this job {job.reclaims} times", "kind": "worker_died"}
            else:
                job.status = "new"
                requeued.append(job.id)
            _notify(session, job)
        session.commit()
    return requeued


def complete(id: int, elapsed: float | None = None, result: dict | None = None) -> None:
    _set(id, status="done", elapsed=elapsed, result=result)


def fail(id: int, error: dict, kind: str, elapsed: float | None = None) -> None:
    _set(id, status="error", error={**error, "kind": kind}, elapsed=elapsed)


def reschedule(id: int, delay: timedelta, because: str, kind: str = "retry", attempts: int | None = None,
               deferred_seconds: int | None = None, elapsed: float | None = None) -> None:
    retry_at = datetime.now(timezone.utc) + delay
    fields = {"status": "new", "apply_since": retry_at, "elapsed": elapsed,
              "waiting_because": {"kind": kind, "error": because, "retry_at": retry_at.isoformat()}}
    if attempts is not None:
        fields["attempts"] = attempts
    if deferred_seconds is not None:
        fields["deferred_seconds"] = deferred_seconds
    _set(id, **fields)


def _set(id: int, **fields) -> None:
    with Session() as session:
        job = session.get(Job, id)
        if job is None:
            return
        # a cancel is final; only how long the job ran is still recorded
        if job.status == "cancelled":
            fields = {k: v for k, v in fields.items() if k == "elapsed"}
        for key, value in fields.items():
            if value is not None or key in ("result", "error"):
                setattr(job, key, value)
        _notify(session, job)
        session.commit()


def get(id: int) -> Job | None:
    with Session() as session:
        return session.get(Job, id)


def is_cancelled(id: int) -> bool:
    job = get(id)
    return job is not None and job.status == "cancelled"


def live_ids(statuses=None, type: str | None = None, run_id: int | None = None, ids=None) -> list[int]:
    query = select(Job.id).where(Job.status.in_([s for s in ACTIVE if not statuses or s in statuses]))
    if type:
        query = query.where(Job.type == type)
    if run_id is not None:
        query = query.where(Job.run_id == run_id)
    if ids:
        query = query.where(Job.id.in_(ids))
    with Session() as session:
        return list(session.scalars(query.order_by(Job.id)))


# after someone looked into a failure: a fresh budget, the error kept in waiting_because
def retry(ids: list[int]) -> list[int]:
    if not ids:
        return []
    with Session() as session:
        jobs = session.scalars(select(Job).where(Job.id.in_(ids), Job.status.in_(("error", "cancelled")))).all()
        for job in jobs:
            job.waiting_because = {"kind": "retried", "previous_error": job.error}
            job.status, job.attempts, job.reclaims, job.error, job.deferred_seconds = "new", 0, 0, None, 0
            job.apply_since = func.now()
            _notify(session, job)
        session.commit()
        return sorted(j.id for j in jobs)


def pause(ids: list[int]) -> list[int]:
    return _move(ids, "new", "paused")


def resume(ids: list[int]) -> list[int]:
    return _move(ids, "paused", "new")


# one statement: a job the worker claims between a read and a write is never held while it runs
def _move(ids: list[int], was: str, to: str) -> list[int]:
    if not ids:
        return []
    with Session() as session:
        moved = session.scalars(
            update(Job).where(Job.id.in_(ids), Job.status == was).values(status=to).returning(Job.id)
        ).all()
        for job_id in moved:
            _notify_raw(session, {"id": job_id, "status": to})
        session.commit()
    return sorted(moved)


# a running job learns of its cancel cooperatively, between chapters or page ranges
def cancel(ids: list[int]) -> list[int]:
    if not ids:
        return []
    with Session() as session:
        tree_ids = {r["id"] for i in ids for r in (dict(x._mapping) for x in session.execute(TREE, {"id": i}))}
        jobs = session.scalars(select(Job).where(Job.id.in_(tree_ids), Job.status.in_(ACTIVE))).all()
        for job in jobs:
            job.status = "cancelled"
            _notify(session, job)
        session.commit()
        return sorted(j.id for j in jobs)


def _notify(session, job: Job) -> None:
    _notify_raw(session, {"id": job.id, "type": job.type, "status": job.status, "run_id": job.run_id,
                          "parent_id": job.parent_id})


def _notify_raw(session, payload: dict) -> None:
    session.execute(text("SELECT pg_notify(:c, :p)"), {"c": CHANNEL, "p": json.dumps(payload)})


TREE = text("""
    WITH RECURSIVE tree AS (
        SELECT id, status, run_id FROM jobs WHERE id = :id
        UNION ALL
        SELECT j.id, j.status, j.run_id FROM jobs j JOIN tree t ON j.parent_id = t.id
    )
    SELECT id, status, run_id FROM tree
""")


def tree(id: int) -> list[dict]:
    with Session() as session:
        return [dict(r._mapping) for r in session.execute(TREE, {"id": id})]


# what a waiting caller gets back: finished, or stopped on a run that needs attention
def settled(id: int) -> dict | None:
    rows = tree(id)
    if not rows:
        return {"finished": True, "missing": True}
    if all(r["status"] in FINISHED for r in rows):
        return {"finished": True}
    run_ids = {r["run_id"] for r in rows if r["run_id"] is not None}
    if run_ids:
        with Session() as session:
            waiting = session.scalars(select(Run.id).where(Run.id.in_(run_ids), Run.status == "needs_attention")).all()
        if waiting:
            return {"finished": False, "needs_attention": sorted(waiting)}
    return None


# listens rather than polls: every state change is announced on the channel
def wait(id: int, timeout: float = 600) -> dict:
    deadline = time.monotonic() + timeout
    url = make_url(settings.DATABASE_URL).set(drivername="postgresql")
    with psycopg.connect(url.render_as_string(hide_password=False), autocommit=True) as conn:
        conn.execute(f"LISTEN {CHANNEL}")
        while True:
            state = settled(id)
            if state is not None:
                return {**state, "tree": tree(id)}
            left = deadline - time.monotonic()
            if left <= 0:
                return {"finished": False, "timeout": True, "tree": tree(id)}
            for _ in conn.notifies(timeout=min(left, 5.0), stop_after=1):
                pass


def stats() -> dict:
    with Session() as session:
        counts = session.execute(select(Job.lane, Job.status, func.count()).group_by(Job.lane, Job.status)).all()
        oldest = session.scalar(select(func.min(Job.apply_since)).where(Job.status == "new"))
        attention = session.scalars(select(Run.id).where(Run.status == "needs_attention")).all()
    out: dict = {}
    for lane, status, n in counts:
        out.setdefault(lane, {})[status] = n
    return {"lanes": out, "oldest_waiting": oldest.isoformat() if oldest else None, "needs_attention": attention}
