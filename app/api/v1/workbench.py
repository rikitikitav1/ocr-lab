from fastapi import APIRouter
from pydantic import BaseModel
from use_cases import workbench

router = APIRouter()


class ReadRange(BaseModel):
    engine: str
    first_page: int
    last_page: int


class Reassemble(BaseModel):
    knobs: dict
    ords: list[int] | None = None


@router.post("/books/{id}/read_range", status_code=202)
def read_range(id: int, body: ReadRange):
    return workbench.read_range(id, body.engine, body.first_page, body.last_page)


@router.post("/runs/{id}/reassemble", status_code=202)
def reassemble(id: int, body: Reassemble):
    return workbench.reassemble(id, body.knobs, body.ords)


@router.get("/artifacts/{id}")
def get_artifact(id: int):
    return workbench.get_artifact(id)


@router.post("/stand/worker/reload")
def reload_worker():
    return workbench.reload_worker()
