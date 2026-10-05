import json
import shutil
import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile
from pydantic import BaseModel
from use_cases import books, metadata

router = APIRouter()


class ShelfSubmission(BaseModel):
    shelf_paths: list[str] = []
    file_paths: list[str] = []
    knobs: dict = {}


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


@router.post("/books")
def add_book(body: ShelfSubmission):
    return books.add_book(body.shelf_paths, body.file_paths, body.knobs)


@router.post("/books/upload")
def upload_book(files: Annotated[list[UploadFile], File()], knobs: Annotated[str, Form()] = "{}"):
    with tempfile.TemporaryDirectory() as tmp:
        sources = []
        for i, f in enumerate(files):
            target = Path(tmp) / f"{i:03d}.pdf"
            with target.open("wb") as out:
                shutil.copyfileobj(f.file, out)
            sources.append((target, f.filename or target.name))
        return books.submit(sources, json.loads(knobs))


@router.post("/books/recollect")
def recollect_books(body: RecollectMany):
    return books.recollect_books(body.ids or None, body.what)


@router.get("/books")
def list_books(stage: str | None = None, verdict: str | None = None, q: str | None = None,
               series: str | None = None, limit: int = 100):
    return books.list_books(stage, verdict, q, series, limit)


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


@router.post("/books/{id}/recollect")
def recollect(id: int, body: Recollect):
    return books.recollect(id, body.what)
