# two structures told apart the same way by every door that compares them: the rows in their order, and the base
from orm.catalogue import StructureNode
from sqlalchemy import select

STRUCTURE_ROW = ("title", "level", "first_page", "last_page", "kind")


def structure_rows(session, version_id: int | None) -> list[tuple]:
    if version_id is None:
        return []
    rows = session.scalars(select(StructureNode).where(StructureNode.structure_version_id == version_id)
                           .order_by(StructureNode.ord))
    return [tuple(getattr(e, k) for k in STRUCTURE_ROW) for e in rows]


# what was removed and added, with the bases; None when the rows stand the same in the same order on one base
def structure_diff(old: list[tuple], new: list[tuple], bases: list, shown: int | None = None) -> dict | None:
    if old == new and bases[0] == bases[1]:
        return None
    removed, added = [r for r in old if r not in new], [r for r in new if r not in old]
    return {"base": bases, "rows": [len(old), len(new)], "removed_total": len(removed), "added_total": len(added),
            "removed": [dict(zip(STRUCTURE_ROW, r, strict=True)) for r in removed[:shown]],
            "added": [dict(zip(STRUCTURE_ROW, r, strict=True)) for r in added[:shown]]}
