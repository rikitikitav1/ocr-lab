# a run's pieces as its structure version gives them, with the pages cut from the bundle
from job_signals import Final
from orm.catalogue import Run, StructureNode
from sqlalchemy import select

from stages import assemble


def rows(session, structure_version_id: int) -> list[dict]:
    entries = session.scalars(select(StructureNode).where(StructureNode.structure_version_id == structure_version_id)
                              .order_by(StructureNode.ord))
    return [{"id": e.id, "ord": e.ord, "title": e.title, "level": e.level, "first_page": e.first_page,
             "last_page": e.last_page, "kind": e.kind, "parent_ord": e.parent_ord} for e in entries]


def cut(session, run: Run) -> dict[str, frozenset[int]]:
    return assemble.cut_pages(run.structure_version_id, rows(session, run.structure_version_id))


def all_cut(session, run: Run) -> frozenset[int]:
    return frozenset().union(*cut(session, run).values())


# no shape signal for a deeper level is found yet, so every book reads its top nodes
def automatic_level(rows: list[dict]) -> int:
    return 0


# the level a new run of the book reads at: the owner's when set, else the one the tree gives
def level_for(owners: int | None, rows: list[dict]) -> int:
    return automatic_level(rows) if owners is None else owners


def pieces(session, run: Run, level: int | None = None, reread: bool = True) -> list[dict]:
    # a reassembly may cut a kept run at another level; the run itself uses the level frozen in it
    level = run.reading_level if level is None else level
    if level is None:
        raise Final(f"run {run.id} was read by chapters, which the tree replaced: its bundle stays, "
                    f"but it is not read or assembled again; start a new run")
    return assemble.pieces_of(rows(session, run.structure_version_id), all_cut(session, run), level, reread)


# a node no unit holds (a part opening on its first child's page) is read and rerun with the unit after it
def holding(units: list[dict], ord: int, first_page: int | None) -> dict | None:
    held = {n["ord"]: u for u in units for n in u["nodes"]}
    after = next((held[o] for o in sorted(held) if o > ord), None)
    return held.get(ord) or (after if after is not None and after["first_page"] == first_page else None)


def piece_entry(session, run: Run, ord: int, level: int | None = None, reread: bool = True) -> dict:
    found = next((c for c in pieces(session, run, level, reread) if c["ord"] == ord), None)
    if found is None:
        raise Final(f"run {run.id} has no piece {ord}")
    return found
