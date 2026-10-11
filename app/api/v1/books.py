import json
import shutil
import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Form, Query, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from use_cases import books, metadata, shelf

router = APIRouter()


class ShelfSubmission(BaseModel):
    shelf_paths: list[str] = []
    file_paths: list[str] = []
    knobs: dict = {}
    then: list[str] | None = None
    order: str = "given"


class KnobChange(BaseModel):
    set: dict = {}
    unset: list[str] = []


class MetadataValue(BaseModel):
    value: object


class Recollect(BaseModel):
    what: list[str] | None = None


class RecollectMany(BaseModel):
    ids: list[int] = []
    what: list[str] | None = None


class ShelfSnapshot(BaseModel):
    book_ids: list[int] = []


def _created(book: dict) -> JSONResponse:
    return JSONResponse(jsonable_encoder(book), status_code=201 if book.get("created") else 200)


# 201 for a new book, 200 when the same files were submitted before
@router.post("/books")
def add_book(body: ShelfSubmission):
    return _created(books.add_book(body.shelf_paths, body.file_paths, body.knobs, body.then, body.order))


@router.post("/books/upload")
def upload_book(files: Annotated[list[UploadFile], File()], knobs: Annotated[str, Form()] = "{}",
                then: Annotated[str, Form()] = ""):
    with tempfile.TemporaryDirectory() as tmp:
        sources = []
        for i, f in enumerate(files):
            target = Path(tmp) / f"{i:03d}.pdf"
            with target.open("wb") as out:
                shutil.copyfileobj(f.file, out)
            sources.append((target, f.filename or target.name))
        return _created(books.submit(sources, json.loads(knobs), json.loads(then) if then else None))


@router.post("/books/recollect", status_code=202)
def recollect_books(body: RecollectMany):
    return books.recollect_books(body.ids or None, body.what)


@router.get("/books")
def list_books(stage: str | None = None, q: str | None = None, series: str | None = None,
               limit: int = 100, offset: int = 0, brief: bool = True):
    return books.list_books(stage, q, series, limit, offset, brief)


@router.post("/shelf/snapshots", status_code=201)
def shelf_snapshot(body: ShelfSnapshot):
    return shelf.shelf_snapshot(body.book_ids or None)


@router.get("/shelf/snapshots/{id}/changes")
def shelf_changes(id: int, book_ids: Annotated[list[int] | None, Query()] = None):
    return shelf.shelf_changes(id, book_ids)


@router.get("/metadata/coverage")
def metadata_coverage():
    return metadata.coverage()


@router.get("/books/{id}")
def get_book(id: int):
    return books.get_book(id)


@router.get("/books/{id}/metadata")
def get_metadata(id: int):
    return metadata.get_metadata(id)


@router.patch("/books/{id}/metadata/{name}")
def set_metadata(id: int, name: str, body: MetadataValue):
    return metadata.set_metadata(id, name, body.value)


@router.patch("/books/{id}/knobs")
def set_book_knobs(id: int, body: KnobChange):
    return books.set_book_knobs(id, body.set, body.unset)


@router.post("/books/{id}/recollect", status_code=202)
def recollect(id: int, body: Recollect):
    return books.recollect(id, body.what)
