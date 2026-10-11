
import job_specs
from mcp_tools import tool
from orm.catalogue import MetadataField
from orm.db import Session
from sqlalchemy import select
from stages.metadata import resolve
from stages.metadata.candidates import FIELDS, OPTIONAL, REQUIRED, SOUGHT
from stages.metadata.fields import view as field_view


@tool("metadata", "GET /v1/books/{id}/metadata",
      "The current metadata fields of a book: value, source, confidence, the attempts that found it, and "
      "whether the field is required or optional.")
def get_metadata(id: int) -> list[dict]:
    version = resolve.current_version(id)
    if version is None:
        raise LookupError(f"book {id} has no metadata yet")
    with Session() as session:
        rows = session.scalars(select(MetadataField).where(MetadataField.metadata_version_id == version.id))
        return [{"name": f.name, "optional": f.name in OPTIONAL, "required": f.name in REQUIRED, **field_view(f),
                 "attempts": f.attempts, "version": version.version} for f in rows]


# the one hand edit the stand accepts; the found values stay in the field's evidence
@tool("set_metadata", "PATCH /v1/books/{id}/metadata/{name}",
      "Sets one metadata field by hand (source manual) and returns the field; the values found before stay in "
      "its evidence.")
def set_metadata(id: int, name: str, value: object) -> dict:
    if name not in FIELDS:
        raise job_specs.Refused(f"unknown metadata field {name!r}; known: {', '.join(FIELDS)}")
    resolve.set_manual(id, name, value)
    return next(r for r in get_metadata(id) if r["name"] == name)


LOW_CONFIDENCE = 0.6


# how complete the catalogue is: per field, and the books still missing a required one
@tool("metadata_coverage", "GET /v1/metadata/coverage",
      "How complete the catalogue is: per field filled, empty, conflicting and low-confidence counts by source,"
      " and the books still missing a required or sought field.")
def coverage() -> dict:
    from orm.catalogue import Book, MetadataVersion

    with Session() as session:
        rows = session.execute(
            select(Book.id, MetadataField).join(MetadataVersion, MetadataVersion.book_id == Book.id)
            .join(MetadataField, MetadataField.metadata_version_id == MetadataVersion.id)
            .where(MetadataVersion.current)).all()
    fields = {name: {"class": "required" if name in REQUIRED else "sought" if name in SOUGHT else "optional",
                     "filled": 0, "empty": 0, "conflict": 0, "low_confidence": 0, "by_source": {}} for name in FIELDS}
    books: dict[int, dict] = {}
    for book_id, f in rows:
        if f.name not in fields:
            continue
        entry = fields[f.name]
        book = books.setdefault(book_id, {"missing": [], "not_found": []})
        if f.value is None:
            entry["empty"] += 1
            if f.name in REQUIRED:
                book["missing"].append(f.name)
            elif f.name in SOUGHT:
                book["not_found"].append(f.name)
            continue
        entry["filled"] += 1
        entry["by_source"][f.source] = entry["by_source"].get(f.source, 0) + 1
        entry["conflict"] += any(a.get("outcome") == "conflict" for a in f.attempts)
        entry["low_confidence"] += (f.confidence or 0) < LOW_CONFIDENCE
    return {"books": len(books), "fields": fields,
            "books_missing_required": {b: v["missing"] for b, v in books.items() if v["missing"]},
            "books_not_found": {b: v["not_found"] for b, v in books.items() if v["not_found"]}}
