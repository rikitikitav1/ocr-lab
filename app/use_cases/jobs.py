import job_handlers
import job_queue
import job_specs
from engines import card
from mcp_tools import tool
from orm.db import Session
from orm.jobs import Job
from sqlalchemy import select
from stages import run_state

from use_cases import runs


def _row(job: Job) -> dict:
    return {"id": job.id, "type": job.type, "lane": job.lane, "status": job.status, "parent_id": job.parent_id,
            "run_id": job.run_id, "book_id": job.book_id, "options": job.options, "attempts": job.attempts,
            "waiting_because": job.waiting_because, "result": job.result, "error": job.error,
            "elapsed": job.elapsed, "code_hash": job.code_hash, "created_at": job.created_at.isoformat()}


@tool("jobs", "GET /v1/jobs",
      "Lists jobs newest first, filtered by status, type, run_id, lane or book_id (see job_types for types), "
      "with options, attempts, waiting_because, result and error.")
def list_jobs(status: str | None = None, type: str | None = None, run_id: int | None = None,
              lane: str | None = None, book_id: int | None = None, limit: int = 100) -> list[dict]:
    query = select(Job).order_by(Job.id.desc()).limit(limit)
    for column, value in (("status", status), ("type", type), ("run_id", run_id), ("lane", lane),
                          ("book_id", book_id)):
        if value is not None:
            query = query.where(getattr(Job, column) == value)
    with Session() as session:
        return [_row(j) for j in session.scalars(query)]


@tool("job", "GET /v1/jobs/{id}",
      "One job with its options, attempts, result and error, and the id and status of every job under it.")
def get_job(id: int) -> dict:
    job = job_queue.get(id)
    if job is None:
        raise LookupError(f"no job {id}")
    return {**_row(job), "tree": job_queue.tree(id)}


BRIEF_ROWS = 50


# a run of many chapters has thousands of jobs, so a wait gives counts and the jobs not done unless asked for all
def _brief(rows: list[dict]) -> dict:
    counts: dict = {}
    for r in rows:
        per_type = counts.setdefault(r["type"], {})
        per_type[r["status"]] = per_type.get(r["status"], 0) + 1
    not_done = sorted((r for r in rows if r["status"] != "done"), key=lambda r: (r["status"] != "error", r["id"]))
    return {"counts": counts, "not_done": not_done[:BRIEF_ROWS], "not_done_total": len(not_done)}


# a run waiting in attention says why, its job errors and failed chapters, so the caller needs no second call
@tool("wait_job", "GET /v1/jobs/{id}/wait",
      "Blocks until a job and the jobs under it finish, its run needs attention, or `timeout` seconds pass. "
      "Returns counts per type and status, the jobs not done (errors first) and why stopped runs stopped; "
      "`tree` returns every job instead.")
def wait_job(id: int, timeout: float = 600, tree: bool = False) -> dict:
    got = job_queue.wait(id, timeout)
    rows = got.pop("tree", None) or []
    run_ids = {r["run_id"] for r in rows if r.get("run_id") is not None}
    if run_ids:
        with Session() as session:
            got["stopped_runs"] = runs.stopped(session, run_ids)
    return {**got, "tree": rows} if tree else {**got, **_brief(rows)}


@tool("pause_jobs", "POST /v1/jobs/pause",
      "Pauses the given queued (new) jobs so the worker leaves them; returns the ids changed.")
def pause_jobs(ids: list[int]) -> dict:
    return {"changed": job_queue.pause(ids)}


@tool("resume_jobs", "POST /v1/jobs/resume",
      "Puts the given paused jobs back in the queue; returns the ids changed.")
def resume_jobs(ids: list[int]) -> dict:
    return {"changed": job_queue.resume(ids)}


@tool("cancel_jobs", "POST /v1/jobs/cancel",
      "Cancels the given jobs and every live job under them; a running one stops at its next check. Returns the"
      " ids changed.")
def cancel_jobs(ids: list[int]) -> dict:
    return {"changed": job_queue.cancel(ids)}


@tool("retry_jobs", "POST /v1/jobs/retry",
      "Gives failed or cancelled jobs a fresh attempt budget and reopens their chapters and runs; returns the "
      "ids changed.")
def retry_jobs(ids: list[int]) -> dict:
    return {"changed": run_state.retry(ids)}


@tool("queue", "GET /v1/queue",
      "Job counts per lane and status, the oldest waiting job, runs needing attention and who holds the GPU.")
def queue() -> dict:
    return {**job_queue.stats(), "gpu_holders": card.holders()}


@tool("job_types", "GET /v1/job_types",
      "Every job type with its lane, attempt budget, options schema and whether the worker can run it yet.")
def job_types() -> list[dict]:
    job_handlers.load_all()
    return job_specs.catalogue(set(job_handlers.HANDLERS))
