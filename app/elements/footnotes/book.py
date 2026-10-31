# the footnote element, learned from the book: the notes block below the body on a page, and its lines as text
import itertools
import re
import statistics
from collections import Counter

from elements import folding

NOTE_MARKER = re.compile(r"^\s*(\d{1,4}(?=\s|[^\W\d])|\*+|[†‡§])\s*(?=[^\W\d]|[\"'(\[«“‘])")
# a notes block stands apart from the body by more than this many of the body's line steps
GAP = 1.3
# a part of a book may be set half a point off its body, so a body line is any size within this of it
SAME = 0.5


def _body_line(x, body: float) -> bool:
    return abs(x.size - body) <= SAME


# the book's usual step from one body line to the next
def _step(lines: dict, pages: list[int], body: float, taken: set[int]) -> float:
    steps = []
    for p in pages:
        tops = sorted(x.top for x in lines[p] if id(x) not in taken and _body_line(x, body))
        steps += [b - a for a, b in itertools.pairwise(tops) if 0 < b - a < 3 * body]
    return statistics.median(steps) if steps else 0.0


# the mark stands in the body's text on a word, after a number's point or comma too, never inside a longer number
def _cited(mark: str, text: str) -> bool:
    if mark.isdigit():
        return bool(re.search(rf"(?<!\d){mark}(?!\d)", text))
    return bool(re.search(rf"\S ?{re.escape(mark)}", text))


# what stands below a page's last body line in a smaller size, and the body's text above it
def _foot(ls: list, body: float) -> tuple[list, object, str]:
    last = max((i for i, x in enumerate(ls) if _body_line(x, body)), default=None)
    if last is None:
        return [], None, ""
    return ([x for x in ls[last + 1:] if x.size < ls[last].size],
            ls[last], " ".join(x.text for x in ls[:last + 1]))


# a page's notes open after a gap with a mark its text cites, and each mark opens one note: code repeats its own
def _opened(below: list, last, text: str, step: float) -> str | None:
    first = next((x for x in below if len(x.text.strip()) > 2), None)
    if first is None or below[0].top - last.top <= GAP * step or not (m := NOTE_MARKER.match(first.text)):
        return None
    opening = [o.group(1) for x in below if (o := NOTE_MARKER.match(x.text))]
    return m.group(1) if opening.count(m.group(1)) == 1 and _cited(m.group(1), text) else None


# a book's notes are numbered in order page to page, or start again at one
def _in_order(marks: list[str]) -> bool:
    nums = [int(m) for m in marks if m.isdigit()]
    pairs = list(itertools.pairwise(nums))
    return not nums or (bool(pairs) and sum(b > a or b == 1 for a, b in pairs) * 2 > len(pairs))


# a line standing word for word at the foot of most pages that have a foot is a notice, a service element of the page
def _notices(feet: dict) -> set[str]:
    seen = Counter(t for below, _, _ in feet.values() for t in {x.text for x in below})
    return {t for t, n in seen.items() if n * 2 > len(feet)} if len(feet) > 1 else set()


# the notes block below a page's last body line read on all its factors at once, with no count of pages, and the notices
def learn(lines: dict, pages: list[int], body: float, taken: set[int],
          size: float | None = None) -> tuple[dict | None, dict, dict]:
    step = _step(lines, pages, body, taken)
    feet = {}
    for p in pages:
        foot = _foot(sorted((x for x in lines[p] if id(x) not in taken), key=lambda x: x.top), body)
        if foot[0]:
            feet[p] = foot
    repeated = _notices(feet)
    notices = {p: kept for p, f in feet.items() if (kept := [x for x in f[0] if x.text in repeated])}
    below_body, marked = {}, {}
    for p, (below, last, text) in feet.items():
        if below := [x for x in below if x.text not in repeated]:
            below_body[p] = below
            if mark := _opened(below, last, text, step):
                marked[p] = mark
    if not marked or not _in_order([marked[p] for p in sorted(marked)]):
        return None, {}, notices
    size = size or Counter(round(x.size * 2) / 2 for p in marked for x in below_body[p]).most_common(1)[0][0]
    # a note running over from the page before has no marker of its own
    kept = {p: b for p, b in below_body.items() if p in marked or (p - 1 in marked and abs(b[0].size - size) <= 0.5)}
    notes = {p: [x for x in b if x.size <= size + 0.5] for p, b in kept.items()}
    notes = {p: b for p, b in notes.items() if any(abs(x.size - size) <= 0.5 for x in b)}
    return {"size": size, "pages": len(notes), "lines": sum(map(len, notes.values()))}, notes, notices


# the lines the page layout reads as notes, per book page, joined and spaced for a word-bounded search
def note_text(lines: dict, notes: set[int]) -> dict[int, str]:
    return {p: f" {folding.fold(' '.join(x.text for x in ls if id(x) in notes))} "
            for p, ls in lines.items() if any(id(x) in notes for x in ls)}
