from fastapi import APIRouter
from pydantic import BaseModel
from use_cases import jobs

router = APIRouter()


class Ids(BaseModel):
    ids: list[int]


@router.get("/jobs")
def list_jobs(status: str | None = None, type: str | None = None, run_id: int | None = None, lane: str | None = None,
              limit: int = 100):
    return jobs.list_jobs(status, type, run_id, lane, limit)


@router.get("/jobs/{id}")
def get_job(id: int):
    return jobs.get_job(id)


@router.get("/jobs/{id}/wait")
def wait_job(id: int, timeout: float = 600):
    return jobs.wait_job(id, timeout)


@router.post("/jobs/pause")
def pause_jobs(body: Ids):
    return jobs.pause_jobs(body.ids)


@router.post("/jobs/resume")
def resume_jobs(body: Ids):
    return jobs.resume_jobs(body.ids)


@router.post("/jobs/cancel")
def cancel_jobs(body: Ids):
    return jobs.cancel_jobs(body.ids)


@router.post("/jobs/retry")
def retry_jobs(body: Ids):
    return jobs.retry_jobs(body.ids)


@router.get("/queue")
def queue():
    return jobs.queue()
