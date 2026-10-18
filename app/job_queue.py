import json
import time
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import job_costs
import job_specs
import psycopg
import settings
import worker_registry
from orm.catalogue import Run, RunStatus
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
running_lane: ContextVar[str | None] = ContextVar("running_lane", default=None)


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
        return _add(session, job)
    with Session() as own:
        id = _add(own, job)
        own.commit()
        return id


# a bulk door's parent: done at once, so waiting on it waits for exactly the jobs queued under it
def batch(session, door: str, books: int) -> int:
    options = job_specs.check("batch", {"door": door, "books": books})
    job = Job(type="batch", lane=job_specs.lane("batch"), options=options, status="done", result=options)
    session.add(job)
    session.flush()
    return job.id


# the parent row is locked, so a cancel either sees this child or this child sees the cancel
def _add(session, job: Job) -> int:
    if job.parent_id is not None:
        parent = session.scalar(select(Job.status).where(Job.id == job.parent_id).with_for_update())
        if parent == "cancelled":
            job.status = "cancelled"
    session.add(job)
    session.flush()
    _notify(session, job)
    return job.id


def claim_next(lane: str, code_hash: str | None = None, host: str | None = None) -> ClaimedJob | None:
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
        job.claimed_by = host
        _notify(session, job)
        claimed = ClaimedJob(job.id, job.type, dict(job.options), job.attempts, job.deferred_seconds, job.run_id,
                             job.book_id)
        session.commit()
        return claimed


# a job in these lanes that could start now, a deferral's wait aside; no lanes (a worker serving none yet) has none
def has_due(lanes: list[str] | None = None) -> bool:
    with Session() as session:
        where = [Job.status == "new", Job.apply_since <= func.now()]
        where += [Job.lane.in_(lanes)] if lanes is not None else []
        return session.scalar(select(Job.id).where(*where).limit(1)) \
            is not None


# jobs left running by a worker whose session is gone, by this host's last life when it starts, and by old code
def requeue_stale(lanes: list[str], host: str | None = None, starting: bool = True, foreign: bool = True) -> list[int]:
    requeued = []
    with Session() as session:
        rows = list(session.scalars(select(Job).where(Job.status == "running", Job.lane.in_(lanes))
                                    .with_for_update(skip_locked=True)))
        claimers = {j.claimed_by for j in rows} - {None, host}
        gone = {h for h in claimers if not worker_registry.host_alive(h)} if foreign else set()
        for job in rows:
            # every claim names its worker, so a running job naming none has no one to finish it
            mine, ownerless = job.claimed_by == host, foreign and job.claimed_by is None
            if mine and not starting or not mine and job.claimed_by not in gone and not ownerless:
                continue
            job.reclaims += 1
            job.claimed_by = None
            if job.reclaims > MAX_RECLAIMS:
                job.status = "error"
                job.error = {"error": f"the worker stopped under this job {job.reclaims} times", "kind": "worker_died"}
            else:
                job.status = "new"
                requeued.append(job.id)
            _notify(session, job)
        session.commit()
    return requeued


# a worker's outcome names it as the claimant: a job another worker took back since is no longer its to settle
def complete(id: int, elapsed: float | None = None, result: dict | None = None, claimant: str | None = None) -> bool:
    return _set(id, claimant, status="done", elapsed=elapsed, result=result)


def fail(id: int, error: dict, kind: str, elapsed: float | None = None, claimant: str | None = None) -> bool:
    return _set(id, claimant, status="error", error={**error, "kind": kind}, elapsed=elapsed)


def reschedule(id: int, delay: timedelta, because: str, kind: str = "retry", attempts: int | None = None,
               deferred_seconds: int | None = None, elapsed: float | None = None, claimant: str | None = None) -> bool:
    retry_at = datetime.now(timezone.utc) + delay
    fields = {"status": "new", "apply_since": retry_at, "elapsed": elapsed, "claimed_by": None,
              "waiting_because": {"kind": kind, "error": because, "retry_at": retry_at.isoformat()}}
    if attempts is not None:
        fields["attempts"] = attempts
    if deferred_seconds is not None:
        fields["deferred_seconds"] = deferred_seconds
    return _set(id, claimant, **fields)


def _set(id: int, claimant: str | None = None, **fields) -> bool:
    with Session() as session:
        # the row is held, so a claim committing meanwhile is seen before a late outcome overwrites it
        job = session.scalar(select(Job).where(Job.id == id).with_for_update())
        if job is None or claimant is not None and job.claimed_by not in (None, claimant):
            return False
        # a cancel is final; only how long the job ran is still recorded
        if job.status == "cancelled":
            fields = {k: v for k, v in fields.items() if k == "elapsed"}
        for key, value in fields.items():
            if value is not None or key in ("result", "error", "claimed_by"):
                setattr(job, key, value)
        _notify(session, job)
        session.commit()
    return True


def get(id: int) -> Job | None:
    with Session() as session:
        return session.get(Job, id)


def is_cancelled(id: int) -> bool:
    job = get(id)
    return job is not None and job.status == "cancelled"


# jobs of a book waiting on a timer for what another job just finished are due at once; the timer stays the fallback
def wake(type: str, book_id: int) -> int:
    with Session() as session:
        jobs = list(session.scalars(select(Job).where(Job.type == type, Job.book_id == book_id, Job.status == "new",
                                                      Job.apply_since > func.now())))
        for job in jobs:
            job.apply_since = func.now()
            _notify(session, job)
        session.commit()
    return len(jobs)


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
def retry(ids: list[int], session=None) -> list[int]:
    if not ids:
        return []
    if session is not None:
        return _retry(session, ids)
    with Session() as own:
        retried = _retry(own, ids)
        own.commit()
        return retried


def _retry(session, ids: list[int]) -> list[int]:
    jobs = session.scalars(select(Job).where(Job.id.in_(ids), Job.status.in_(("error", "cancelled")))).all()
    for job in jobs:
        job.waiting_because = {"kind": "retried", "previous_error": job.error}
        job.status, job.attempts, job.reclaims, job.error, job.deferred_seconds = "new", 0, 0, None, 0
        job.apply_since = func.now()
        _notify(session, job)
    session.flush()
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


# a running job learns of its cancel cooperatively, between pieces or page ranges
def cancel(ids: list[int]) -> list[int]:
    if not ids:
        return []
    with Session() as session:
        tree_ids: set[int] = set()
        # locked rows take no new children, so the tree read again after locking is complete
        while True:
            found = {r["id"] for i in ids for r in (dict(x._mapping) for x in session.execute(TREE, {"id": i}))}
            if found == tree_ids:
                break
            session.execute(select(Job.id).where(Job.id.in_(found - tree_ids)).with_for_update())
            tree_ids = found
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
        SELECT id, type, status, run_id, book_id FROM jobs WHERE id = :id
        UNION ALL
        SELECT j.id, j.type, j.status, j.run_id, j.book_id FROM jobs j JOIN tree t ON j.parent_id = t.id
    )
    SELECT id, type, status, run_id, book_id FROM tree
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
            waiting = session.scalars(select(Run.id).where(Run.id.in_(run_ids),
                                                           Run.status == RunStatus.ATTENTION)).all()
        if waiting:
            return {"finished": False, "needs_attention": sorted(waiting)}
    return None


# listens rather than polls: every job change wakes it, and a check every 5 s catches state no job announces
def listen(check: Callable[[], dict | None], timeout: float) -> dict | None:
    deadline = time.monotonic() + timeout
    url = make_url(settings.DATABASE_URL).set(drivername="postgresql")
    with psycopg.connect(url.render_as_string(hide_password=False), autocommit=True) as conn:
        conn.execute(f"LISTEN {CHANNEL}")
        while True:
            state = check()
            if state is not None:
                return state
            left = deadline - time.monotonic()
            if left <= 0:
                return None
            for _ in conn.notifies(timeout=min(left, 5.0), stop_after=1):
                pass


def wait(id: int, timeout: float = 600) -> dict:
    state = listen(lambda: settled(id), timeout)
    if state is None:
        return {"finished": False, "timeout": True, "tree": tree(id)}
    return {**state, "tree": tree(id)}


def stats(book_ids: list[int] | None = None, types: list[str] | None = None) -> dict:
    with Session() as session:
        counts = session.execute(select(Job.lane, Job.status, func.count()).group_by(Job.lane, Job.status)).all()
        oldest = session.scalar(select(func.min(Job.apply_since)).where(Job.status == "new"))
        attention = session.scalars(select(Run.id).where(Run.status == RunStatus.ATTENTION)).all()
        live = select(Job).where(Job.status.in_(ACTIVE))
        live = live.where(Job.book_id.in_(book_ids)) if book_ids else live
        live = live.where(Job.type.in_(types)) if types else live
        active = list(session.scalars(live.order_by(Job.id)))
        now = session.scalar(select(func.now()))
    out: dict = {}
    for lane, status, n in counts:
        out.setdefault(lane, {})[status] = n
    in_flight: dict = {}
    for job in active:
        lane = in_flight.setdefault(job.lane, {})
        lane.setdefault(job.type, {}).setdefault(job.status, 0)
        lane[job.type][job.status] += 1
    running = [{"id": j.id, "type": j.type, "lane": j.lane, "book_id": j.book_id, "run_id": j.run_id,
                "seconds": round((now - j.updated_at).total_seconds(), 1)} for j in active if j.status == "running"]
    return {"lanes": out, "oldest_waiting": oldest.isoformat() if oldest else None, "needs_attention": attention,
            "in_flight": in_flight, "running": running, "seconds_left": job_costs.seconds_left(active, running)}
