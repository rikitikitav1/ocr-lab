from fastapi import APIRouter
from use_cases import toc

router = APIRouter()


@router.get("/books/{id}/toc")
def get_toc(id: int, source: str | None = None, version: int | None = None):
    return toc.get_toc(id, source, version)
