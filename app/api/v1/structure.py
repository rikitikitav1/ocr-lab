from fastapi import APIRouter
from use_cases import structure

router = APIRouter()


@router.get("/books/{id}/structure")
def get_structure(id: int, source: str | None = None, version: int | None = None):
    return structure.get_structure(id, source, version)
