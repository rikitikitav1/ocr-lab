from mcp_tools import tool
from orm.catalogue import TocEntry, TocVersion
from orm.db import Session
from sqlalchemy import select
from stages.toc import evidence

SOURCES = ("bookmarks", "printed_contents")


def _version(session, book_id: int, version: int | None) -> TocVersion:
    query = select(TocVersion).where(TocVersion.book_id == book_id)
    query = query.where(TocVersion.version == version) if version is not None else query.where(TocVersion.current)
    found = session.scalar(query)
    if found is None:
        raise LookupError(f"book {book_id} has no toc" + (f" version {version}" if version is not None else " yet"))
    return found


# the chosen entries with their page ranges, or one source's raw list as the stage read it
@tool("toc", "GET /v1/books/{id}/toc",
      "A book's table of contents: the chosen entries with level and page range for the current or a given "
      "version, or with `source` (bookmarks, printed_contents) that source's raw list as the stage read it.")
def get_toc(id: int, source: str | None = None, version: int | None = None) -> dict:
    if source is not None and source not in SOURCES:
        raise LookupError(f"unknown toc source {source!r}; known: {', '.join(SOURCES)}")
    with Session() as session:
        found = _version(session, id, version)
        kept = evidence.read(session, found.id)
        head = {"book_id": id, "version": found.version, "created_at": found.created_at,
                "chosen": (kept or {}).get("chosen")}
        if source is None:
            rows = session.scalars(select(TocEntry).where(TocEntry.toc_version_id == found.id).order_by(TocEntry.ord))
            return {**head, "entries": [{"ord": e.ord, "title": e.title, "level": e.level,
                                         "level_source": e.level_source, "first_page": e.first_page,
                                         "last_page": e.last_page, "kind": e.kind, "votes": e.votes} for e in rows]}
    if kept is None:
        raise LookupError(f"toc version {head['version']} of book {id} kept no evidence; collect it again")
    return {**head, "source": kept.get(source),
            "placement": kept.get("placement") if source == "printed_contents" else None}
