from fastapi import APIRouter
from pydantic import BaseModel
from use_cases import structure

router = APIRouter()


@router.get("/books/{id}/structure")
def get_structure(id: int, source: str | None = None, version: int | None = None):
    return structure.get_structure(id, source, version)


class Preview(BaseModel):
    book_ids: list[int]
    knobs: dict = {}


@router.post("/structure/preview", status_code=202)
def structure_preview(body: Preview):
    return structure.structure_preview(body.book_ids, body.knobs)
