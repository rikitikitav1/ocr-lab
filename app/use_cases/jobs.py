import job_queue
from mcp_tools import tool
from orm.db import Session
from orm.jobs import Job
from sqlalchemy import select


def _row(job: Job) -> dict:
    return {"id": job.id, "type": job.type, "lane": job.lane, "status": job.status, "parent_id": job.parent_id,
            "run_id": job.run_id, "book_id": job.book_id, "options": job.options, "attempts": job.attempts,
            "waiting_because": job.waiting_because, "result": job.result, "error": job.error,
            "elapsed": job.elapsed, "code_hash": job.code_hash, "created_at": job.created_at.isoformat()}


@tool("jobs", "GET /v1/jobs")
def list_jobs(status: str | None = None, type: str | None = None, run_id: int | None = None,
              lane: str | None = None, limit: int = 100) -> list[dict]:
    query = select(Job).order_by(Job.id.desc()).limit(limit)
    for column, value in (("status", status), ("type", type), ("run_id", run_id), ("lane", lane)):
        if value is not None:
            query = query.where(getattr(Job, column) == value)
    with Session() as session:
        return [_row(j) for j in session.scalars(query)]


@tool("job", "GET /v1/jobs/{id}")
def get_job(id: int) -> dict:
    job = job_queue.get(id)
    if job is None:
        raise LookupError(f"no job {id}")
    return {**_row(job), "tree": job_queue.tree(id)}


@tool("wait_job", "GET /v1/jobs/{id}/wait")
def wait_job(id: int, timeout: float = 600) -> dict:
    return job_queue.wait(id, timeout)


@tool("pause_jobs", "POST /v1/jobs/pause")
def pause_jobs(ids: list[int]) -> dict:
    return {"changed": job_queue.pause(ids)}


@tool("resume_jobs", "POST /v1/jobs/resume")
def resume_jobs(ids: list[int]) -> dict:
    return {"changed": job_queue.resume(ids)}


@tool("cancel_jobs", "POST /v1/jobs/cancel")
def cancel_jobs(ids: list[int]) -> dict:
    return {"changed": job_queue.cancel(ids)}


@tool("retry_jobs", "POST /v1/jobs/retry")
def retry_jobs(ids: list[int]) -> dict:
    return {"changed": job_queue.retry(ids)}


@tool("queue", "GET /v1/queue")
def queue() -> dict:
    return job_queue.stats()
