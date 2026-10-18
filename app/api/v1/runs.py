import mimetypes
from typing import Annotated

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel
from use_cases import cleanup, pages, runs

router = APIRouter()


class StartRun(BaseModel):
    format: str = "markdown"
    profile_id: int | None = None
    search: bool = True


@router.post("/books/{id}/runs", status_code=202)
def start_run(id: int, body: StartRun):
    return runs.start_run(id, body.format, body.profile_id, body.search)


class StartRuns(BaseModel):
    book_ids: list[int]
    format: str = "markdown"


@router.post("/runs", status_code=202)
def start_runs(body: StartRuns):
    return runs.start_runs(body.book_ids, body.format)


class CancelRuns(BaseModel):
    ids: list[int]
    dry_run: bool = False


@router.post("/runs/cancel")
def cancel_runs(body: CancelRuns):
    return runs.cancel_runs(body.ids, body.dry_run)


@router.get("/runs")
def list_runs(ids: Annotated[list[int] | None, Query()] = None, book_id: int | None = None, status: str | None = None,
              limit: int = 50):
    return runs.list_runs(ids, book_id, status, limit)


# the fixed paths come before /runs/{id}, which would otherwise take them as an id
@router.get("/runs/wait")
def wait_runs(ids: Annotated[list[int], Query()], timeout: float = 600, until: str = "all"):
    return runs.wait_runs(ids, timeout, until)


class Pairs(BaseModel):
    pairs: list[list[int]]
    lines: int = 5


@router.post("/runs/compare")
def compare_run_pairs(body: Pairs):
    return runs.compare_run_pairs(body.pairs, body.lines)


@router.get("/runs/compare")
def compare_runs(a: int, b: int, keys: Annotated[list[str] | None, Query()] = None):
    return runs.compare_runs(a, b, keys)


@router.get("/runs/{id}")
def get_run(id: int):
    return runs.get_run(id)


@router.get("/runs/{id}/nodes")
def run_pieces(id: int, brief: bool = False):
    return runs.run_pieces(id, brief)


@router.get("/runs/{id}/pages/{page}")
def run_page(id: int, page: int):
    return pages.page(id, page)


@router.get("/runs/{id}/report")
def run_report(id: int, pieces: bool = False):
    return runs.run_report(id, pieces)


@router.get("/runs/{id}/artifacts")
def run_artifacts(id: int, stage: str | None = None, node: int | None = None, used: bool = False,
                  heavy: bool = False, name: str | None = None):
    return runs.run_artifacts(id, stage, node, used, heavy, name)


@router.get("/runs/{id}/artifacts/{artifact_id}")
def run_artifact(id: int, artifact_id: int):
    name, data = runs.artifact_file(id, artifact_id)
    return Response(data, media_type=mimetypes.guess_type(name)[0] or "application/octet-stream")


def _tar(name: str, data: bytes) -> Response:
    disposition = {"Content-Disposition": f'attachment; filename="{name}"'}
    return Response(data, media_type="application/x-tar", headers=disposition)


@router.get("/runs/{id}/bundle")
def run_bundle(id: int):
    return _tar(*runs.bundle_tar(id))


@router.get("/books/{id}/bundle")
def book_bundle(id: int):
    return _tar(*runs.book_bundle_tar(id))


class Rerun(BaseModel):
    overrides: dict | None = None


@router.post("/runs/{id}/nodes/{ord}/rerun", status_code=202)
def rerun_node(id: int, ord: int, body: Rerun):
    return runs.rerun_node(id, ord, body.overrides)


@router.post("/runs/{id}/resume", status_code=202)
def resume_run(id: int):
    return runs.resume_run(id)


@router.delete("/runs/{id}")
def delete_run(id: int):
    return cleanup.delete_run(id)


class Cleanup(BaseModel):
    dry_run: bool = True


@router.post("/cleanup")
def run_cleanup(body: Cleanup):
    return cleanup.cleanup(body.dry_run)


@router.post("/runs/{id}/cancel")
def cancel_run(id: int):
    return runs.cancel_run(id)
