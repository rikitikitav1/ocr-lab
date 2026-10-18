# a book's page layout from its text layer, learned from the book: the body's size, the running slots, the notes
import re
import statistics
from collections import Counter

import numerals

NOTE_MARKER = re.compile(r"^\s*(\d{1,4}|[*†‡§])\s*\S")
FOLIO = re.compile(r"^\s*(\d{1,4})\s+\S|\S\s+(\d{1,4})\s*$|^\s*(\d{1,4})\s*$")
ROMAN_FOLIO = re.compile(rf"^\s*({numerals.ROMAN})\s+\S|\S\s+({numerals.ROMAN})\s*$|^\s*({numerals.ROMAN})\s*$")
ROMAN_MAX = 60
BAND = 30
MIN_PAGES = 10


def _picks(lines: dict, pages: list[int], edge, exclude: set[int]) -> dict:
    picks = {p: edge([x for x in lines[p] if id(x) not in exclude]) for p in pages}
    return {p: x for p, x in picks.items() if x is not None}


def _fits(x, size: float, weight: bool | None) -> bool:
    return abs(x.size - size) <= 0.5 and (weight is None or x.bold == weight)


def _claim(picks: dict, size: float, weight: bool | None, lo: float, hi: float) -> dict:
    return {p: x for p, x in picks.items() if _fits(x, size, weight) and lo <= x.top <= hi}


def _slot(lines: dict, pages: list[int], edge, exclude: set[int]) -> tuple[dict | None, dict]:
    picks = _picks(lines, pages, edge, exclude)
    if not picks:
        return None, {}
    size = Counter(round(x.size * 2) / 2 for x in picks.values()).most_common(1)[0][0]
    same = [x for x in picks.values() if abs(x.size - size) <= 0.5]
    bold, held = Counter(x.bold for x in same).most_common(1)[0]
    # a weight counts only when nine of ten slot lines keep it, running heads may change it
    weight = bold if held * 10 >= len(same) * 9 else None
    # the densest band, so two page sizes in one book do not spread it
    tops = sorted(x.top for x in picks.values() if _fits(x, size, weight))
    start, best = 0, (0, 0)
    for i in range(len(tops)):
        while tops[i] - tops[start] > BAND:
            start += 1
        best = max(best, (i - start + 1, start))
    lo, hi = tops[best[1]], tops[best[1] + best[0] - 1]
    claimed = _claim(picks, size, weight, lo, hi)
    if len(claimed) * 2 <= len(pages):
        return None, {}
    bare = Counter(re.sub(r"\d+", "", x.text).strip() for x in claimed.values())
    repeat = round(sum(n for n in bare.values() if n >= 3) / len(claimed), 2)
    offsets, sides = Counter(), Counter()
    for p, x in claimed.items():
        if m := FOLIO.search(x.text):
            offsets[p - int(next(g for g in m.groups() if g))] += 1
            sides[(p % 2, "first" if m.group(1) else "last" if m.group(2) else "alone")] += 1
    folio = offsets.most_common(1)[0] if offsets else None
    folio = folio if folio and folio[1] >= 3 and folio[1] * 2 >= len(claimed) else None
    front = _roman(claimed, folio[0]) if folio else None
    # a band of body lines neither numbers the pages nor repeats
    if not folio and repeat < 0.5:
        return None, {}
    return {"size": size, "bold": weight, "band": [round(lo), round(hi)], "pages": len(claimed),
            "words": statistics.median(len(x.text.split()) for x in claimed.values()), "repeat": repeat,
            "folio": {"offset": folio[0], "pages": folio[1]} if folio else None, "roman": front,
            "sides": {f"{'odd' if k[0] else 'even'}_{k[1]}": v for k, v in sorted(sides.items()) if v >= 3}}, claimed


def _notes(lines: dict, pages: list[int], body: int, taken: set[int],
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


def _roman_value(text: str) -> int | None:
    m = ROMAN_FOLIO.search(text)
    value = numerals.roman(next(g for g in m.groups() if g)) if m else None
    return value if value and value <= ROMAN_MAX else None


def _arabic(x, p: int, offset: int) -> bool:
    m = FOLIO.search(x.text)
    return bool(m) and p - int(next(g for g in m.groups() if g)) == offset


# the front matter numbers its pages in roman numerals, its own sequence before the first arabic folio
def _roman(claimed: dict, offset: int) -> dict | None:
    before = min((p for p, x in claimed.items() if _arabic(x, p, offset)), default=None)
    if before is None:
        return None
    offsets = Counter(p - v for p, x in claimed.items() if p < before and (v := _roman_value(x.text)))
    best = offsets.most_common(1)[0] if offsets else None
    return {"offset": best[0], "pages": best[1], "before": before} if best and best[1] >= 3 else None


def measure(lines: dict) -> tuple[dict, set[int]]:
    pages = sorted(p for p in lines if lines[p])
    if len(pages) < MIN_PAGES:
        return {"skipped": f"{len(pages)} pages with lines"}, set()
    body = statistics.mode(round(x.size) for p in pages for x in lines[p])
    # a head set on its side is often a page's first line in reading order: aside before the top and bottom picks
    turned = {id(x) for p in pages for x in lines[p] if x.turned}
    top, top_lines = _slot(lines, pages, _top, turned)
    taken = {id(x) for x in top_lines.values()}
    bottom, bottom_lines = _slot(lines, pages, _bottom, taken | turned)
    taken |= {id(x) for x in bottom_lines.values()}
    sides, side_lines = _sides(lines, pages)
    taken |= side_lines
    notes, note_lines = _notes(lines, pages, body, taken)
    taken |= {id(x) for b in note_lines.values() for x in b}
    return {"pages": len(pages), "body": body, "top": top, "bottom": bottom, "sides": sides, "notes": notes}, taken


SIDE_GAP, SIDE_SHARE, SIDE_WIDTH = 50.0, 3, 3
# a page with more turned lines than this holds a turned table or is set landscape, so it gives no side head
SIDE_PER_PAGE = 3


# heads set on their side, one band per edge (x apart by more than SIDE_GAP), kept when one text repeats on 3 pages
def _sides(lines: dict, pages: list[int]) -> tuple[list[dict], set[int]]:
    on_page = {p: [x for x in lines[p] if x.turned] for p in pages}
    turned = sorted((x for ls in on_page.values() if len(ls) <= SIDE_PER_PAGE for x in ls), key=lambda x: x.x)
    groups: list[list] = []
    for x in turned:
        if groups and x.x - groups[-1][-1].x <= SIDE_GAP:
            groups[-1].append(x)
        else:
            groups.append([x])
    out, taken = [], set()
    for group in groups:
        size = Counter(round(x.size * 2) / 2 for x in group).most_common(1)[0][0]
        same = [x for x in group if abs(x.size - size) <= 0.5]
        bare = Counter(re.sub(r"\d+", "", x.text).strip() for x in same)
        lo, hi = min(x.x for x in same), max(x.x for x in same)
        repeat = round(sum(n for n in bare.values() if n >= SIDE_SHARE) / len(same), 2)
        # a turned table or caption on a landscape page spreads across it; a head keeps to a narrow band and repeats
        if hi - lo > SIDE_WIDTH * size or repeat < 0.5:
            continue
        out.append({"size": size, "band": [round(lo), round(hi)], "lines": len(same), "repeat": repeat})
        taken |= {id(x) for x in same}
    return out, taken


def _top(ls: list):
    return min(ls, key=lambda x: x.top) if ls else None


def _bottom(ls: list):
    return max(ls, key=lambda x: x.top) if ls else None


# the lines a kept layout's slots hold again by their stored band and size: per top and bottom slot, and on the sides
def _held(lines: dict, layout: dict, pages: list[int]) -> tuple[list[tuple[dict, dict]], list]:
    turned = {id(x) for p in pages for x in lines[p] if x.turned}
    taken: set[int] = set()
    edges = []
    for edge, slot in ((_top, layout.get("top")), (_bottom, layout.get("bottom"))):
        if not slot:
            continue
        # the band is kept in whole points, so half a point either side covers the rounding
        lo, hi = slot["band"]
        got = _claim(_picks(lines, pages, edge, taken | turned), slot["size"], slot["bold"], lo - 0.5, hi + 0.5)
        taken |= {id(x) for x in got.values()}
        edges.append((slot, got))
    sides = [x for side in layout.get("sides") or [] for p in pages for x in lines[p] if x.turned
             and abs(x.size - side["size"]) <= 0.5 and side["band"][0] - 0.5 <= x.x <= side["band"][1] + 0.5]
    return edges, sides


# slot lines by reason (folio, repeat, side); one in a band by place and size alone has none: it may be body text
def claimed_reasons(lines: dict, layout: dict) -> dict[int, tuple[object, str]]:
    edges, sides = _held(lines, layout, sorted(p for p in lines if lines[p]))
    out: dict[int, tuple[object, str]] = {}
    for slot, got in edges:
        bare = Counter(re.sub(r"\d+", "", x.text).strip() for x in got.values())
        offset = (slot.get("folio") or {}).get("offset")
        front = slot.get("roman")
        for p, x in got.items():
            if offset is not None and _arabic(x, p, offset):
                out[id(x)] = (x, "folio")
            elif front and p < front["before"] and (v := _roman_value(x.text)) and p - v == front["offset"]:
                out[id(x)] = (x, "folio")
            elif bare[re.sub(r"\d+", "", x.text).strip()] >= SIDE_SHARE:
                out[id(x)] = (x, "repeat")
    out |= {id(x): (x, "side") for x in sides}
    return out


# the slot and note lines of a kept page layout, claimed again by its stored band and sizes, nothing learned twice
def claimed(lines: dict, layout: dict) -> set[int]:
    pages = sorted(p for p in lines if lines[p])
    edges, sides = _held(lines, layout, pages)
    taken = {id(x) for _, got in edges for x in got.values()} | {id(x) for x in sides}
    if layout.get("notes"):
        _, notes = _notes(lines, pages, layout["body"], taken, layout["notes"]["size"])
        taken |= {id(x) for b in notes.values() for x in b}
    return taken
