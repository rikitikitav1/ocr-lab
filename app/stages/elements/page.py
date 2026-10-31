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


# the slot and note lines of a kept page layout, claimed again by its stored band and sizes, nothing learned twice
def claimed(lines: dict, layout: dict) -> set[int]:
    pages = sorted(p for p in lines if lines[p])
    taken = slots.claimed(lines, layout, pages)
    if layout.get("notes") or layout.get("notices"):
        size = layout["notes"]["size"] if layout.get("notes") else None
        _, notes, notices = footnotes.learn(lines, pages, layout["body"], taken, size)
        taken |= {id(x) for b in (*notes.values(), *notices.values()) for x in b}
    return taken
