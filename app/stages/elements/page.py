# a book's page layout from its text layer, learned from the book: the body's size, the running slots, the notes
import statistics

from elements.footnotes import book as footnotes
from elements.running_heads import slots

MIN_PAGES = 10


def measure(lines: dict) -> tuple[dict, set[int]]:
    pages = sorted(p for p in lines if lines[p])
    if len(pages) < MIN_PAGES:
        return {"skipped": f"{len(pages)} pages with lines"}, set()
    body = statistics.mode(round(x.size) for p in pages for x in lines[p])
    top, bottom, sides, taken = slots.learn(lines, pages)
    notes, note_lines = footnotes.learn(lines, pages, body, taken)
    taken |= {id(x) for b in note_lines.values() for x in b}
    return {"pages": len(pages), "body": body, "top": top, "bottom": bottom, "sides": sides, "notes": notes}, taken


# the slot and note lines of a kept page layout, claimed again by its stored band and sizes, nothing learned twice
def claimed(lines: dict, layout: dict) -> set[int]:
    pages = sorted(p for p in lines if lines[p])
    taken = slots.claimed(lines, layout, pages)
    if layout.get("notes"):
        _, notes = footnotes.learn(lines, pages, layout["body"], taken, layout["notes"]["size"])
        taken |= {id(x) for b in notes.values() for x in b}
    return taken
