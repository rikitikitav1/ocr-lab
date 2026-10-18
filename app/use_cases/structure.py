import book_knobs
import job_queue
import job_specs
from mcp_tools import tool
from orm.catalogue import StructureNode, StructureVersion
from orm.db import Session
from sqlalchemy import select
from stages.structure import evidence

from use_cases import known

SOURCES = ("bookmarks", "printed_contents")


def _version(session, book_id: int, version: int | None) -> StructureVersion:
    query = select(StructureVersion).where(StructureVersion.book_id == book_id)
    query = query.where(StructureVersion.version == version) if version is not None \
        else query.where(StructureVersion.current)
    found = session.scalar(query)
    if found is None:
        which = f" version {version}" if version is not None else " yet"
        raise LookupError(f"book {book_id} has no structure" + which)
    return found


# the chosen entries with their page ranges, or one source's raw list as the stage read it
@tool("structure", "GET /v1/books/{id}/structure",
      "A book's structure: the chosen nodes with level, parent and page range for the current or a given "
      "version, or with `source` (bookmarks, printed_contents) that source's raw list as the stage read it.")
def get_structure(id: int, source: str | None = None, version: int | None = None) -> dict:
    if source is not None and source not in SOURCES:
        raise LookupError(f"unknown structure source {source!r}; known: {', '.join(SOURCES)}")
    with Session() as session:
        found = _version(session, id, version)
        kept = evidence.read(session, found.id)
        head = {"book_id": id, "version": found.version, "created_at": found.created_at,
                "chosen": (kept or {}).get("chosen"), "depth": found.depth}
        if source is None:
            rows = session.scalars(select(StructureNode).where(StructureNode.structure_version_id == found.id)
                                   .order_by(StructureNode.ord))
            return {**head, "entries": [{"ord": e.ord, "title": e.title, "level": e.level,
                                         "level_source": e.level_source, "first_page": e.first_page,
                                         "last_page": e.last_page, "kind": e.kind, "parent_ord": e.parent_ord,
                                         "votes": e.votes} for e in rows]}
    if kept is None:
        raise LookupError(f"structure version {head['version']} of book {id} kept no evidence; collect it again")
    return {**head, "source": kept.get(source),
            "placement": kept.get("placement") if source == "printed_contents" else None}


@tool("structure_preview", "POST /v1/structure/preview",
      "Collects the structure of the given text books on today's code with `knobs` (book knobs) tried over their own, "
      "writes no version, and answers in the job's result per book whether it moved against the current version "
      "(base, row counts, the first rows removed and added); scans are skipped, and so is the last try by headings "
      "read as pictures unless `structure.from_headings` is set true. Returns {job_id}: follow it with "
      "wait_job, then read the job.")
def structure_preview(book_ids: list[int], knobs: dict | None = None) -> dict:
    if not book_ids:
        raise job_specs.Refused("no books given")
    with Session() as session:
        known.check_books(session, book_ids)
    book_knobs.check(knobs or {})
    return {"job_id": job_queue.enqueue("structure_preview", {"book_ids": book_ids, "knobs": knobs or {}})}
