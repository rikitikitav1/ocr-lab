# a book's two layouts kept as versions: the page layout before the structure, the heading layout after it
import artifacts
import code_version
import settings
import text_layer
from orm.catalogue import LayoutVersion, StructureNode, StructureVersion
from orm.db import Session
from sqlalchemy import func, select, update

from stages import intake, versions
from stages.layout import headings, page
from stages.structure import collect as structure_collect
from stages.structure.sources import book_lines

PAGE, HEADINGS = "page", "headings"


def code_hash() -> str:
    own = [*sorted((settings.APP_DIR / "stages" / "layout").rglob("*.py")),
           settings.APP_DIR / "stages" / "structure" / "sources" / "__init__.py", settings.APP_DIR / "numerals.py",
           settings.APP_DIR / "assembly" / "titles.py"]
    return code_version.files_hash(own).hexdigest()[:16]


def inputs(book_id: int, kind: str, structure_version_id: int | None = None) -> artifacts.Inputs:
    parts = {"stage": f"layout_{kind}", "code": code_hash(), "files": [f.sha256 for f in intake.files_of(book_id)]}
    # the heading layout is made again when the structure or the page layout under it changes
    if kind == HEADINGS:
        page_version = current(book_id, PAGE)
        parts["structure_version_id"] = structure_version_id
        parts["page_version_id"] = page_version.id if page_version else None
    return artifacts.Inputs(parts)


def current(book_id: int, kind: str) -> LayoutVersion | None:
    with Session() as session:
        return session.scalar(select(LayoutVersion).where(LayoutVersion.book_id == book_id, LayoutVersion.kind == kind,
                                                          LayoutVersion.current))


def _write(book_id: int, kind: str, made_from: artifacts.Inputs, layout: dict, job_id: int | None,
           structure_version_id: int | None = None) -> int:
    with Session() as session:
        versions.lock_book(session, book_id)
        mine = (LayoutVersion.book_id == book_id) & (LayoutVersion.kind == kind)
        number = (session.scalar(select(func.max(LayoutVersion.version)).where(mine)) or 0) + 1
        session.execute(update(LayoutVersion).where(mine).values(current=False))
        version = LayoutVersion(book_id=book_id, kind=kind, version=number, input_hash=made_from.key, job_id=job_id,
                                current=True, structure_version_id=structure_version_id, layout=layout)
        session.add(version)
        session.commit()
        return version.id


def _kept(book_id: int, kind: str, made_from: artifacts.Inputs, force: bool) -> int | None:
    previous = current(book_id, kind)
    return previous.id if previous and previous.input_hash == made_from.key and not force else None


def _lines(book_id: int) -> dict | None:
    # a scan has no text layer to measure; its layout from the engines' boxes is not built yet
    return None if structure_collect.scanned(book_id) else book_lines(intake.files_of(book_id))


# a layout made from other inputs than today's: its code, the files, and for the heading layout the structure under it
def stale(book_id: int, kind: str) -> bool:
    previous = current(book_id, kind)
    if previous is None:
        return False
    structure_version_id = _nodes(book_id)[0] if kind == HEADINGS else None
    return previous.input_hash != inputs(book_id, kind, structure_version_id).key


def collect_page(book_id: int, job_id: int | None = None, force: bool = False) -> int:
    made_from = inputs(book_id, PAGE)
    if (kept := _kept(book_id, PAGE, made_from, force)) is not None:
        return kept
    lines = _lines(book_id)
    if lines is None:
        layout = {"skipped": "a scan"}
    else:
        paths = [settings.DATA_DIR / f.file_path for f in intake.files_of(book_id)]
        layout = {**page.measure(lines)[0], "monospace": text_layer.monospace(paths)}
    return _write(book_id, PAGE, made_from, layout, job_id)


def _nodes(book_id: int) -> tuple[int | None, list[dict]]:
    with Session() as session:
        structure = versions.current(session, StructureVersion, book_id)
        if structure is None:
            return None, []
        rows = session.scalars(select(StructureNode).where(StructureNode.structure_version_id == structure.id)
                               .order_by(StructureNode.ord))
        return structure.id, [{"title": r.title, "level": r.level, "first_page": r.first_page} for r in rows
                        if r.kind != "front_matter" and r.first_page is not None]


def collect_headings(book_id: int, job_id: int | None = None, force: bool = False) -> int | None:
    structure_version_id, nodes = _nodes(book_id)
    if structure_version_id is None:
        return None
    made_from = inputs(book_id, HEADINGS, structure_version_id)
    if (kept := _kept(book_id, HEADINGS, made_from, force)) is not None:
        return kept
    kept_page = current(book_id, PAGE)
    if kept_page is None or "skipped" in kept_page.layout:
        layout = {"skipped": kept_page.layout["skipped"] if kept_page else "no page layout yet"}
    else:
        lines = book_lines(intake.files_of(book_id))
        layout = headings.measure(lines, page.claimed(lines, kept_page.layout), nodes)
    return _write(book_id, HEADINGS, made_from, layout, job_id, structure_version_id)
