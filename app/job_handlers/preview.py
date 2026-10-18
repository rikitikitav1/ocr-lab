# a structure collected on today's code with knobs tried, compared with each book's current version, written nowhere
import book_knobs
from job_signals import Final
from orm.db import Session
from stages import intake
from stages.structure import collect, compare, evidence

from job_handlers import register

SHOWN = 10


def _one(book_id: int) -> dict:
    if collect.scanned(book_id):
        return {"skipped": "a scan's contents are read on the GPU lane; preview takes text books"}
    try:
        source, entries, found = collect.choose(book_id)
    except Final as e:
        return {"failed": str(e)}
    new = [tuple(r[k] for k in compare.STRUCTURE_ROW)
           for r in collect.structure_rows(entries, source, found["pages"], intake.files_of(book_id))]
    current = collect.current_version(book_id)
    with Session() as session:
        old = compare.structure_rows(session, current.id) if current else []
        base = evidence.base(session, current.id) if current else None
    moved = compare.structure_diff(old, new, [base, source], SHOWN)
    return {"same": moved is None, **(moved or {"base": [base, source], "rows": [len(old), len(new)],
                                                "removed_total": 0, "added_total": 0, "removed": [], "added": []})}


# the headings of a book read as pictures need MinerU on the GPU lane, so a preview leaves them off unless asked
@register("structure_preview")
def run_preview(options: dict) -> dict:
    token = book_knobs.trying.set({"structure.from_headings": False, **(options.get("knobs") or {})})
    try:
        books = {str(b): _one(b) for b in options["book_ids"]}
    finally:
        book_knobs.trying.reset(token)
    moved = [int(b) for b, r in books.items() if r.get("same") is False]
    return {"knobs": options.get("knobs") or {}, "books": books, "moved": moved,
            "skipped": [int(b) for b, r in books.items() if "skipped" in r],
            "failed": [int(b) for b, r in books.items() if "failed" in r]}
