from mcp_tools import tool
from orm.catalogue import LayoutVersion
from orm.db import Session
from sqlalchemy import select

KINDS = ("page", "headings")


@tool("layout", "GET /v1/books/{id}/layout",
      "A book's layout learned from its text layer, current or a given `version`: `kind` page (gathered before the "
      "structure: body size, running slots at the top and bottom with their folio, notes, the monospace share) "
      "or headings (gathered after it: "
      "each structure level's style at its nodes and the label above them). A run pins the page layout version it "
      "starts on: the assembly reads its running slots and notes, the preset choice and the report its monospace "
      "share. Nothing reads the headings layout yet.")
def get_layout(id: int, kind: str = "page", version: int | None = None) -> dict:
    if kind not in KINDS:
        raise LookupError(f"unknown layout kind {kind!r}; known: {', '.join(KINDS)}")
    with Session() as session:
        query = select(LayoutVersion).where(LayoutVersion.book_id == id, LayoutVersion.kind == kind)
        which = LayoutVersion.version == version if version is not None else LayoutVersion.current
        found = session.scalar(query.where(which))
        if found is None:
            asked = f" version {version}" if version is not None else " yet"
            raise LookupError(f"book {id} has no {kind} layout{asked}")
        return {"book_id": id, "kind": kind, "version": found.version, "created_at": found.created_at,
                "structure_version_id": found.structure_version_id, **found.layout}
