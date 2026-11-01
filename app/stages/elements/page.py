# a book's page layout from its text layer, learned from the book: the body's size, the running slots, the notes
from elements import body as body_element
from elements.footnotes import book as footnotes
from elements.running_heads import slots

MIN_PAGES = 10


def measure(lines: dict) -> tuple[dict, set[int]]:
    pages = sorted(p for p in lines if lines[p])
    if len(pages) < MIN_PAGES:
        return {"skipped": f"{len(pages)} pages with lines"}, set()
    top, bottom, sides, taken = slots.learn(lines, pages)
    body = body_element.learn(lines, frozenset(taken))[0]
    notes, note_lines, notices = footnotes.learn(lines, pages, body, taken)
    taken |= {id(x) for b in (*note_lines.values(), *notices.values()) for x in b}
    return {"pages": len(pages), "body": body, "top": top, "bottom": bottom, "sides": sides, "notes": notes,
            "notices": sum(map(len, notices.values()))}, taken


# the note and notice lines of a kept page layout, learned again under its stored note size
def _foot(lines: dict, layout: dict, pages: list[int], taken: set[int]) -> tuple[dict, dict]:
    size = layout["notes"]["size"] if layout.get("notes") else None
    _, notes, notices = footnotes.learn(lines, pages, layout["body"], taken, size)
    return notes, notices


# the note lines alone of a kept page layout: a notice repeated at the foot is no note
def note_lines(lines: dict, layout: dict) -> set[int]:
    if not layout.get("notes"):
        return set()
    pages = sorted(p for p in lines if lines[p])
    notes, _ = _foot(lines, layout, pages, slots.claimed(lines, layout, pages))
    return {id(x) for b in notes.values() for x in b}


# the slot and note lines of a kept page layout, claimed again by its stored band and sizes
def claimed(lines: dict, layout: dict) -> set[int]:
    pages = sorted(p for p in lines if lines[p])
    taken = slots.claimed(lines, layout, pages)
    if layout.get("notes") or layout.get("notices"):
        notes, notices = _foot(lines, layout, pages, taken)
        taken |= {id(x) for b in (*notes.values(), *notices.values()) for x in b}
    return taken


# the service lines a kept page layout claims, by reason: the slots' (folio, repeat, side) and the notices
def service_lines(lines: dict, layout: dict) -> dict[int, tuple[object, str]]:
    out = slots.claimed_reasons(lines, layout)
    if layout.get("notices"):
        pages = sorted(p for p in lines if lines[p])
        _, notices = _foot(lines, layout, pages, slots.claimed(lines, layout, pages))
        out |= {id(x): (x, "notice") for b in notices.values() for x in b}
    return out
