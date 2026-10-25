# a structure gate: each book's structure as choose gives it, kept as a record, two records compared book by book
from engines import card
from job_signals import Deferred, Final
from stages.structure import collect

SHOWN = 5


# a scan whose contents need the card is skipped, not waited on: the gate reads what the CPU reads
def entry(book_id: int, off: tuple[str, ...] = ()) -> dict:
    try:
        source, got, _ = collect.choose(book_id, off)
    except (card.WrongLane, Deferred) as e:
        # the reason's text carries retry times, so the kind alone keeps two records comparable
        return {"skipped": type(e).__name__}
    except Final as e:
        return {"failed": str(e)[:300]}
    return {"source": source, "entries": [[e.title, e.level, e.page] for e in got]}


def _titles(rows: list[list]) -> list[str]:
    return [f"{t} ({level}, p{page})" for t, level, page in rows[:SHOWN]]


# a book moves on its source, its failure or skip, or any entry by title, level and page
def compare(base: dict, new: dict) -> tuple[int, list[str]]:
    moved, lines = 0, []
    for book in sorted(base.keys() | new.keys(), key=int):
        a, b = base.get(book), new.get(book)
        if a == b:
            continue
        moved += 1
        if a is None or b is None:
            lines.append(f"{book} only in {'the base' if b is None else 'the new record'}")
            continue
        if "entries" not in a or "entries" not in b:
            said = b.get("failed") or b.get("skipped") or b["source"]
            lines.append(f"{book} {next(iter(a))} -> {next(iter(b))}: {said}")
            continue
        old, now = [tuple(e) for e in a["entries"]], [tuple(e) for e in b["entries"]]
        gone, added = [list(e) for e in old if e not in now], [list(e) for e in now if e not in old]
        if not gone and not added:
            lines.append(f"{book} {a['source']} -> {b['source']}: the same entries in another order")
            continue
        lines.append(f"{book} {a['source']} -> {b['source']}: {len(old)} -> {len(now)} entries, "
                     f"gone {len(gone)} {_titles(gone)}, added {len(added)} {_titles(added)}")
    lines.append(f"books moved: {moved} of {len(base.keys() | new.keys())}")
    return moved, lines
