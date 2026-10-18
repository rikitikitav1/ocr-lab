from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel
from use_cases import jobs

router = APIRouter()


class Ids(BaseModel):
    ids: list[int]


@router.get("/jobs")
def list_jobs(status: Annotated[list[str] | None, Query()] = None, type: Annotated[list[str] | None, Query()] = None,
              run_id: Annotated[list[int] | None, Query()] = None, lane: str | None = None,
              book_id: Annotated[list[int] | None, Query()] = None, limit: int = 100, parent_id: int | None = None,
              before_id: int | None = None, brief: bool = False):
    return jobs.list_jobs(status, type, run_id, lane, book_id, limit, parent_id, before_id, brief)


@router.get("/jobs/{id}")
def get_job(id: int):
    return jobs.get_job(id)


@router.get("/jobs/{id}/wait")
def wait_job(id: int, timeout: float = 600, tree: bool = False):
    return jobs.wait_job(id, timeout, tree)


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
def queue(book_ids: Annotated[list[int] | None, Query()] = None, types: Annotated[list[str] | None, Query()] = None):
    return jobs.queue(book_ids, types)


@router.get("/job_types")
def job_types():
    return jobs.job_types()
