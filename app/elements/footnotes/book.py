# the footnote element, learned from the book: the notes block below the body on a page, and its lines as text
import re
from collections import Counter

from elements import folding

NOTE_MARKER = re.compile(r"^\s*(\d{1,4}|[*†‡§])\s*\S")


# the notes block below a page's last body line, smaller than the body and opened by a marker
def learn(lines: dict, pages: list[int], body: int, taken: set[int],
          size: float | None = None) -> tuple[dict | None, dict]:
    below_body = {}
    for p in pages:
        ls = sorted((x for x in lines[p] if id(x) not in taken), key=lambda x: x.top)
        last = max((i for i, x in enumerate(ls) if round(x.size) == body), default=None)
        if last is not None and (below := [x for x in ls[last + 1:] if x.size < body - 0.5]):
            below_body[p] = below
    # a notes block opens with a marker on its first real line, a formula's index is too short to be one
    marked = {p: b for p, b in below_body.items()
              if NOTE_MARKER.match(next((x.text for x in b if len(x.text.strip()) > 2), ""))}
    if not marked:
        return None, {}
    size = size or Counter(round(x.size * 2) / 2 for b in marked.values() for x in b).most_common(1)[0][0]
    # a note running over from the page before has no marker of its own
    kept = {p: b for p, b in below_body.items() if p in marked or (p - 1 in marked and abs(b[0].size - size) <= 0.5)}
    notes = {p: [x for x in b if x.size <= size + 0.5] for p, b in kept.items()}
    notes = {p: b for p, b in notes.items() if any(abs(x.size - size) <= 0.5 for x in b)}
    return {"size": size, "pages": len(notes), "lines": sum(map(len, notes.values()))}, notes


# the lines the page layout reads as notes, per book page, joined and spaced for a word-bounded search
def note_text(lines: dict, notes: set[int]) -> dict[int, str]:
    return {p: f" {folding.fold(' '.join(x.text for x in ls if id(x) in notes))} "
            for p, ls in lines.items() if any(id(x) in notes for x in ls)}
