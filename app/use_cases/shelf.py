import json
from datetime import UTC, datetime

import settings
from mcp_tools import tool
from orm.catalogue import Book, LayoutVersion, MetadataField, MetadataVersion, StructureVersion
from orm.db import Session
from sqlalchemy import select
from stages.structure import evidence
from stages.structure.compare import structure_diff, structure_rows

from use_cases import known


def _dir():
    return settings.DATA_DIR / "snapshots"


def _current(session, model, book_ids: list[int] | None, kind: str | None = None) -> dict[int, int]:
    query = select(model.book_id, model.version).where(model.current)
    if book_ids:
        query = query.where(model.book_id.in_(book_ids))
    query = query.where(model.kind == kind) if kind else query
    return dict(session.execute(query).all())


# the versions a snapshot keeps per book; a layout recollected moves its versions though no node moves
def _versions(session, books: list[int]) -> dict[int, dict]:
    kept = {"structure": _current(session, StructureVersion, books),
            "metadata": _current(session, MetadataVersion, books),
            "layout_page": _current(session, LayoutVersion, books, "page"),
            "layout_headings": _current(session, LayoutVersion, books, "headings")}
    return {b: {name: versions.get(b) for name, versions in kept.items()} for b in books}


# versions are never deleted, so a snapshot keeps only which structure and metadata version each book had
@tool("shelf_snapshot", "POST /v1/shelf/snapshots",
      "Record the current structure, metadata and layout (page, headings) versions of a set of books (all by "
      "default) as a numbered snapshot, to compare against after a change.")
def shelf_snapshot(book_ids: list[int] | None = None) -> dict:
    with Session() as session:
        known.check_books(session, book_ids or [])
        books = list(session.scalars(select(Book.id).where(Book.id.in_(book_ids)) if book_ids else select(Book.id)))
        kept = _versions(session, books)
    taken = {"taken_at": datetime.now(UTC).isoformat(), "books": {str(b): kept[b] for b in sorted(books)}}
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


def _structure_change(session, book_id: int, before: int | None, after: int | None) -> dict | None:
    ids = [_version_id(session, StructureVersion, book_id, v) for v in (before, after)]
    bases = [evidence.base(session, i) if i is not None else None for i in ids]
    moved = structure_diff(*(structure_rows(session, i) for i in ids), bases)
    return {"version": [before, after], **moved} if moved else None


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
      "The books whose structure nodes, structure base or metadata values moved since a snapshot, with what moved "
      "and their layout versions; books whose layouts alone got new versions are listed apart in layouts_moved, and "
      "with_new_versions counts every book with any new version.")
def shelf_changes(id: int, book_ids: list[int] | None = None) -> dict:
    path = _dir() / f"{id}.json"
    if not path.is_file():
        raise LookupError(f"no shelf snapshot {id}")
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    taken = {int(b): v for b, v in snapshot["books"].items() if not book_ids or int(b) in book_ids}
    moved, new_versions, layouts_only = [], 0, {}
    with Session() as session:
        ids = list(taken)
        current = _versions(session, ids)
        for book_id, before in sorted(taken.items()):
            # a snapshot taken before layouts were kept compares what it has
            now = {name: current[book_id][name] for name in before}
            if now == before:
                continue
            new_versions += 1
            change = {"structure": _structure_change(session, book_id, before["structure"], now["structure"])
                      if now["structure"] != before["structure"] else None,
                      "metadata": _metadata_change(session, book_id, before["metadata"], now["metadata"])
                      if now["metadata"] != before["metadata"] else None}
            layouts = {name: [before[name], now[name]] for name in ("layout_page", "layout_headings")
                       if name in before and before[name] != now[name]}
            if change["structure"] or change["metadata"]:
                moved.append({"book_id": book_id, **change, **({"layouts": layouts} if layouts else {})})
            elif layouts:
                layouts_only[book_id] = layouts
    return {"snapshot": id, "taken_at": snapshot["taken_at"], "books": len(taken),
            "with_new_versions": new_versions, "moved": moved, "layouts_moved": layouts_only}


@tool("shelf_snapshots", "GET /v1/shelf/snapshots",
      "The shelf snapshots taken so far: id, when, how many books.")
def shelf_snapshots() -> list[dict]:
    out = []
    for path in sorted((p for p in _dir().glob("*.json") if p.stem.isdigit()), key=lambda p: int(p.stem)):
        kept = json.loads(path.read_text(encoding="utf-8"))
        out.append({"id": kept["id"], "taken_at": kept["taken_at"], "books": len(kept["books"])})
    return out


@tool("shelf_snapshot_read", "GET /v1/shelf/snapshots/{id}",
      "One shelf snapshot: per book the structure, metadata and layout versions it recorded.")
def shelf_snapshot_read(id: int) -> dict:
    path = _dir() / f"{id}.json"
    if not path.is_file():
        raise LookupError(f"no shelf snapshot {id}")
    return json.loads(path.read_text(encoding="utf-8"))
