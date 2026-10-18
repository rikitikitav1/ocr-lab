import job_specs
from fastapi import APIRouter
from pydantic import BaseModel, Field
from use_cases import workbench

router = APIRouter()


class ReadRange(BaseModel):
    engine: str
    first_page: int
    last_page: int
    force_raster_only: bool = False


class Reassemble(BaseModel):
    knobs: dict
    ords: list[int] | None = None
    reading_level: int | None = Field(None, ge=0, le=job_specs.MAX_READING_LEVEL)
    reread: bool = True


@router.post("/books/{id}/read_range", status_code=202)
def read_range(id: int, body: ReadRange):
    return workbench.read_range(id, body.engine, body.first_page, body.last_page, body.force_raster_only)


@router.post("/runs/{id}/reassemble", status_code=202)
def reassemble(id: int, body: Reassemble):
    return workbench.reassemble(id, body.knobs, body.ords, body.reading_level, body.reread)


@router.get("/artifacts/{id}")
def get_artifact(id: int):
    return workbench.get_artifact(id)

