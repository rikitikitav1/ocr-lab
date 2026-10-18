# a run's state from its pieces and their jobs: when to assemble a piece, when the run moves on
import job_queue
import job_specs
import settings
from orm.catalogue import Piece, Run, RunStage, RunStatus
from orm.db import Session
from orm.jobs import Job
from sqlalchemy import select

ENGINES = settings.ENGINES
OPEN = ("new", "running", "paused")


def _round(job: Job) -> int:
    return int(job.options.get("round", 0))


# a piece's jobs of its latest round: a rerun's state is never read off the jobs of the round before it
def jobs_of(session, run_id: int, ord: int) -> list[Job]:
    jobs = list(session.scalars(select(Job).where(Job.run_id == run_id, Job.options["ord"].astext == str(ord))))
    last = max((_round(j) for j in jobs), default=0)
    return [j for j in jobs if _round(j) == last]


# the readings a piece's done read jobs of its latest round made or found, by range, and the builds that made them
def round_readings(session, run_id: int, ord: int) -> tuple[dict[str, int], dict[str, dict]]:
    readings: dict[str, int] = {}
    builds: dict[str, dict] = {}
    for job in jobs_of(session, run_id, ord):
        if job.type == "read_piece" and job.status == "done":
            readings.update((job.result or {}).get("readings") or {})
            builds[job.options["engine"]] = (job.result or {}).get("build")
    return readings, builds


def _both_read(jobs: list[Job]) -> bool:
    return {j.options["engine"] for j in jobs if j.type == "read_piece" and j.status == "done"} >= set(ENGINES)


# what a door or the worker's settling queues for a run hangs under the run's book_run job, so it shows in its tree
def _parent(session, run_id: int) -> int | None:
    if (running := job_queue.running_job.get()) is not None:
        return running
    return session.scalar(select(Job.id).where(Job.run_id == run_id, Job.type == "book_run", Job.status != "cancelled")
                          .order_by(Job.id.desc()).limit(1))


def _enqueue(session, run: Run, type: str, options: dict) -> int:
    return job_queue.enqueue(type, options, parent_id=_parent(session, run.id), run_id=run.id, book_id=run.book_id,
                             session=session)


def _enqueue_assembly(session, run_id: int, ord: int, piece: Piece, jobs: list[Job]) -> None:
    piece.status = "running"
    _enqueue(session, session.get(Run, run_id), "assemble_piece",
             {"run_id": run_id, "ord": ord, "round": max(map(_round, jobs), default=0)})


# the piece after each one in a run read by the tree, by its piece rows; a run by pieces waits for none
def next_ords(session, run: Run) -> dict[int, int]:
    if run.reading_level is None:
        return {}
    ords = list(session.scalars(select(Piece.ord).where(Piece.run_id == run.id).order_by(Piece.ord)))
    return dict(zip(ords, ords[1:], strict=False))


# a piece takes its tail on the next one's first page from the next one's reading, so it waits for those reads
def _neighbour_read(session, run_id: int, nxt: int | None) -> bool:
    return nxt is None or not any(j.type == "read_piece" and j.status in OPEN for j in jobs_of(session, run_id, nxt))


# once both engines read a piece and its next piece's reads ended, its assembly goes on the queue, once
def assemble_when_read(run_id: int, ord: int) -> None:
    with Session() as session:
        following = next_ords(session, session.get(Run, run_id))
        # this read may be the last one a previous piece waited for
        for o in sorted({ord, *(p for p, n in following.items() if n == ord)}):
            piece = session.scalar(select(Piece).where(Piece.run_id == run_id, Piece.ord == o)
                                     .with_for_update())
            jobs = jobs_of(session, run_id, o) if piece is not None else []
            if piece is not None and piece.status == "pending" and _both_read(jobs) \
                    and _neighbour_read(session, run_id, following.get(o)):
                _enqueue_assembly(session, run_id, o, piece, jobs)
        session.commit()


def fail(run_id: int, ord: int, error: str | None) -> None:
    with Session() as session:
        piece = session.get(Piece, (run_id, ord))
        if piece is not None and piece.status != "failed":
            piece.status, piece.errors = "failed", [{"error": error}]
            session.commit()


# an open piece whose jobs all ended: read but never assembled is assembled now, anything else failed
def _reconcile(session, run_id: int) -> None:
    following = next_ords(session, session.get(Run, run_id))
    # the piece rows are locked like assemble_when_read locks them, so the two never queue one assembly twice
    for piece in session.scalars(select(Piece).where(Piece.run_id == run_id,
                                                         Piece.status.in_(("pending", "running")))
                                   .with_for_update()):
        jobs = jobs_of(session, run_id, piece.ord)
        if not jobs or any(j.status in OPEN for j in jobs):
            continue
        if any(j.type == "assemble_piece" and j.status == "done" for j in jobs):
            continue
        if piece.status == "pending" and _both_read(jobs) and not any(j.type == "assemble_piece" for j in jobs):
            if _neighbour_read(session, run_id, following.get(piece.ord)):
                _enqueue_assembly(session, run_id, piece.ord, piece, jobs)
            continue
        ended = [j for j in jobs if j.status in ("error", "cancelled")]
        piece.status = "failed"
        piece.errors = [{"error": f"{j.type} {j.id} {j.status}"} for j in ended] or [{"error": "no job left"}]


# the last piece to end moves the run on: to its metrics when every piece is done, else to attention
def finish(run_id: int) -> None:
    with Session() as session:
        run = session.scalar(select(Run).where(Run.id == run_id).with_for_update())
        if run is None or run.stage != RunStage.ASSEMBLE:
            return
        _reconcile(session, run_id)
        statuses = list(session.scalars(select(Piece.status).where(Piece.run_id == run_id)))
        if any(s in ("pending", "running") for s in statuses):
            session.commit()
            return
        if "failed" in statuses:
            to_attention(run)
        else:
            run.stage = RunStage.METRICS
            _enqueue(session, run, "book_metrics", {"run_id": run_id})
        session.commit()


# runs whose open pieces wait on no live job: a cancel or a dead worker ended their jobs without the ending hooks
def settle() -> list[int]:
    live = select(Job.id).where(Job.run_id == Run.id, Job.status.in_(OPEN)).exists()
    with Session() as session:
        stuck = list(session.scalars(select(Run.id).where(Run.stage == RunStage.ASSEMBLE, ~live).order_by(Run.id)))
    for run_id in stuck:
        finish(run_id)
    return stuck


# a piece read and assembled again: its readings are kept, so only the assembly costs anything
def _restart(session, run: Run, piece: Piece) -> None:
    piece.status, piece.errors = "pending", []
    next_round = max(map(_round, jobs_of(session, run.id, piece.ord)), default=0) + 1
    for engine in ENGINES:
        _enqueue(session, run, "read_piece", {"run_id": run.id, "ord": piece.ord, "engine": engine,
                                                "round": next_round})


def busy(run: Run) -> bool:
    return run.stage in (RunStage.ASSEMBLE, RunStage.METRICS) and run.status == RunStatus.RUNNING


def start(run: Run) -> None:
    run.status, run.stage = RunStatus.RUNNING, RunStage.ASSEMBLE


def to_attention(run: Run) -> None:
    run.status, run.stage = RunStatus.ATTENTION, RunStage.ATTENTION


# a bundle that failed for good leaves the run where resume_run picks it up, as a failed piece does
def metrics_failed(run_id: int) -> None:
    with Session() as session:
        run = session.scalar(select(Run).where(Run.id == run_id).with_for_update())
        if run is not None and run.stage == RunStage.METRICS:
            to_attention(run)
            session.commit()


def to_done(run: Run, bundle_dir: str) -> None:
    run.status, run.stage, run.bundle_dir = RunStatus.DONE, RunStage.DONE, bundle_dir


def _locked(session, run_id: int) -> Run:
    run = session.scalar(select(Run).where(Run.id == run_id).with_for_update())
    if run is None:
        raise LookupError(f"no run {run_id}")
    return run


def _reopen(session, run_id: int) -> Run:
    run = _locked(session, run_id)
    if busy(run):
        raise job_specs.Busy(run_id)
    start(run)
    return run


# a profile given with the rerun becomes the run's under the same lock that reopens it
def rerun_piece(run_id: int, ord: int, profile_id: int | None = None) -> None:
    with Session() as session:
        run = _reopen(session, run_id)
        piece = session.get(Piece, (run_id, ord))
        if piece is None:
            raise LookupError(f"run {run_id} has no piece {ord}")
        if profile_id is not None:
            run.profile_id = profile_id
        _restart(session, run, piece)
        session.commit()


# a stopped run goes on with the pieces not done, and the done ones `changed` says were made from other inputs
def resume(run_id: int, changed=None) -> list[int]:
    with Session() as session:
        run = _reopen(session, run_id)
        # with no piece taken from the structure there is nothing to resume, and the metrics would bundle an empty book
        if session.scalar(select(Piece.ord).where(Piece.run_id == run_id).limit(1)) is None:
            raise ValueError(f"run {run_id} has no pieces: it stopped before taking them from its structure; "
                             f"start a new run")
        pieces = [p for p in session.scalars(select(Piece).where(Piece.run_id == run_id).order_by(Piece.ord))
                  if p.status != "done" or (changed is not None and changed(session, run, p.ord))]
        for piece in pieces:
            _restart(session, run, piece)
        if not pieces:
            run.stage = RunStage.METRICS
            _enqueue(session, run, "book_metrics", {"run_id": run_id})
        session.commit()
        return [c.ord for c in pieces]


# what a retried job's piece goes back to: a read waits for its engines again, an assembly is under way
RETRIED_CHAPTER = {"read_piece": "pending", "assemble_piece": "running"}


# a failed job among the piece's latest, back on the queue, reopens the piece and the run as a rerun does
def _reopen_for(session, run: Run, job: Job) -> None:
    if job.type == "book_metrics" and run.status == RunStatus.ATTENTION:
        run.status, run.stage = RunStatus.RUNNING, RunStage.METRICS
        return
    if job.type not in RETRIED_CHAPTER:
        return
    ord = job.options["ord"]
    piece = session.scalar(select(Piece).where(Piece.run_id == run.id, Piece.ord == ord).with_for_update())
    if piece is None or piece.status != "failed" or job.id not in {j.id for j in jobs_of(session, run.id, ord)}:
        return
    piece.status, piece.errors = RETRIED_CHAPTER[job.type], []
    if not busy(run):
        start(run)


# the job queue's retry door for a run's jobs: their runs are locked first, as the ending hooks lock them
def retry(ids: list[int]) -> list[int]:
    with Session() as session:
        run_ids = sorted(set(session.scalars(select(Job.run_id).where(Job.id.in_(ids), Job.run_id.is_not(None)))))
        runs = {run_id: _locked(session, run_id) for run_id in run_ids}
        retried = job_queue.retry(ids, session=session)
        for job in session.scalars(select(Job).where(Job.id.in_(retried), Job.run_id.is_not(None))
                                   .order_by(Job.id)):
            _reopen_for(session, runs[job.run_id], job)
        session.commit()
    return retried


def cancel(run_id: int) -> list[int]:
    stopped = job_queue.cancel(job_queue.live_ids(run_id=run_id))
    with Session() as session:
        run = session.scalar(select(Run).where(Run.id == run_id).with_for_update())
        if run is None:
            raise LookupError(f"no run {run_id}")
        for piece in session.scalars(select(Piece).where(Piece.run_id == run_id,
                                                             Piece.status.in_(("pending", "running")))):
            piece.status, piece.errors = "failed", [{"error": "cancelled"}]
        run.status, run.stage = RunStatus.CANCELLED, RunStage.CANCELLED
        session.commit()
    return stopped
