import json
from datetime import UTC, datetime

import settings
from mcp_tools import tool
from orm.catalogue import Book, MetadataField, MetadataVersion, StructureNode, StructureVersion
from orm.db import Session
from sqlalchemy import select
from stages.structure import evidence

STRUCTURE_ROW = ("title", "level", "first_page", "last_page", "kind")


def _dir():
    return settings.DATA_DIR / "snapshots"


def _current(session, model, book_ids: list[int] | None) -> dict[int, int]:
    query = select(model.book_id, model.version).where(model.current)
    if book_ids:
        query = query.where(model.book_id.in_(book_ids))
    return dict(session.execute(query).all())


# versions are never deleted, so a snapshot keeps only which structure and metadata version each book had
@tool("shelf_snapshot", "POST /v1/shelf/snapshots",
      "Record the current structure and metadata versions of a set of books (all by default) as a numbered snapshot, to"
      " compare against after a change.")
def shelf_snapshot(book_ids: list[int] | None = None) -> dict:
    with Session() as session:
        books = list(session.scalars(select(Book.id).where(Book.id.in_(book_ids)) if book_ids else select(Book.id)))
        if missing := sorted(set(book_ids or []) - set(books)):
            raise LookupError(f"no books {missing}")
        structure, meta = _current(session, StructureVersion, books), _current(session, MetadataVersion, books)
    taken = {"taken_at": datetime.now(UTC).isoformat(),
             "books": {str(b): {"structure": structure.get(b), "metadata": meta.get(b)} for b in sorted(books)}}
    _dir().mkdir(parents=True, exist_ok=True)
    number = max((int(p.stem) for p in _dir().glob("*.json") if p.stem.isdigit()), default=0) + 1
    # an exclusive create, so two snapshots taken at once never share a number
    while True:
        try:
            with (_dir() / f"{number}.json").open("x", encoding="utf-8") as f:
                json.dump({"id": number, **taken}, f)
            break
        except FileExistsError:
            number += 1
    return {"id": number, "taken_at": taken["taken_at"], "books": len(books)}


def _version_id(session, model, book_id: int, version: int | None) -> int | None:
    if version is None:
        return None
    return session.scalar(select(model.id).where(model.book_id == book_id, model.version == version))


def _structure_rows(session, version_id: int | None) -> list[tuple]:
    if version_id is None:
        return []
    rows = session.scalars(select(StructureNode).where(StructureNode.structure_version_id == version_id)
                           .order_by(StructureNode.ord))
    return [tuple(getattr(e, k) for k in STRUCTURE_ROW) for e in rows]


def _structure_change(session, book_id: int, before: int | None, after: int | None) -> dict | None:
    ids = [_version_id(session, StructureVersion, book_id, v) for v in (before, after)]
    old, new = (_structure_rows(session, i) for i in ids)
    bases = [evidence.base(session, i) if i is not None else None for i in ids]
    if old == new and bases[0] == bases[1]:
        return None
    return {"version": [before, after], "base": bases, "rows": [len(old), len(new)],
            "removed": [dict(zip(STRUCTURE_ROW, r, strict=True)) for r in old if r not in new],
            "added": [dict(zip(STRUCTURE_ROW, r, strict=True)) for r in new if r not in old]}


def _fields(session, version_id: int | None) -> dict:
    if version_id is None:
        return {}
    rows = session.scalars(select(MetadataField).where(MetadataField.metadata_version_id == version_id))
    return {f.name: {"value": f.value, "source": f.source} for f in rows}


def _metadata_change(session, book_id: int, before: int | None, after: int | None) -> dict | None:
    old, new = (_fields(session, _version_id(session, MetadataVersion, book_id, v)) for v in (before, after))
    fields = {name: {"before": old.get(name), "after": new.get(name)} for name in sorted(old.keys() | new.keys())
              if (old.get(name) or {}).get("value") != (new.get(name) or {}).get("value")}
    return {"version": [before, after], "fields": fields} if fields else None


# the books whose structure nodes or metadata values differ now from the snapshot; a new version alone is no change
@tool("shelf_changes", "GET /v1/shelf/snapshots/{id}/changes",
      "The books whose structure nodes, structure base or metadata values moved since a snapshot, with what moved.")
def shelf_changes(id: int, book_ids: list[int] | None = None) -> dict:
    path = _dir() / f"{id}.json"
    if not path.is_file():
        raise LookupError(f"no shelf snapshot {id}")
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    taken = {int(b): v for b, v in snapshot["books"].items() if not book_ids or int(b) in book_ids}
    moved, new_versions = [], 0
    with Session() as session:
        ids = list(taken)
        structure, meta = _current(session, StructureVersion, ids), _current(session, MetadataVersion, ids)
        for book_id, before in sorted(taken.items()):
            now = {"structure": structure.get(book_id), "metadata": meta.get(book_id)}
            if now == before:
                continue
            new_versions += 1
            change = {"structure": _structure_change(session, book_id, before["structure"], now["structure"])
                      if now["structure"] != before["structure"] else None,
                      "metadata": _metadata_change(session, book_id, before["metadata"], now["metadata"])
                      if now["metadata"] != before["metadata"] else None}
            if change["structure"] or change["metadata"]:
                moved.append({"book_id": book_id, **change})
    return {"snapshot": id, "taken_at": snapshot["taken_at"], "books": len(taken),
            "with_new_versions": new_versions, "moved": moved}
