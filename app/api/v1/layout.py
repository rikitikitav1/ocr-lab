from fastapi import APIRouter
from use_cases import layout

router = APIRouter()


@router.get("/books/{id}/layout")
def get_layout(id: int, kind: str = "page", version: int | None = None):
    return layout.get_layout(id, kind, version)
