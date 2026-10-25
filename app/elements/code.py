# the code element: a listing rebuilt from the layer, code an engine read as prose, a listing the page cut, line numbers
import re
import statistics
from collections import Counter
from collections.abc import Callable

from document.model import Code, PageMarker, Paragraph

from elements import geometry

SPREAD = 0.1
_NUMBER = re.compile(r"^(\s*)(\d+)(\s+)(?=\S)")

# glyphs of one advance as a monospace face sets them: nine in ten near the median, so a number column does not count
def uniform(widths: list[float], spread: float = SPREAD) -> bool:
    middle = statistics.median(widths) if widths else 0
    if middle <= 0:
        return False
    return sum(1 for w in widths if abs(w - middle) / middle <= spread) >= 0.9 * len(widths)


def line_number(line: str) -> int | None:
    found = _NUMBER.match(line)
    return int(found.group(2)) if found else None


# a listing is numbered when this many of its lines, at least, carry rising numbers
NUMBERED_MIN_LINES, NUMBERED_SHARE = 3, 0.8


# a listing's line-number column is not code; it goes when nearly every row carries one in order
def line_numbers(lines: list[str]) -> list[int] | None:
    numbered = [n for n in map(line_number, lines) if n is not None]
    if len(lines) < NUMBERED_MIN_LINES or len(numbered) < NUMBERED_SHARE * len(lines) or numbered != sorted(numbered):
        return None
    return numbered


def _without_numbers(lines: list[str]) -> list[str]:
    found = [_NUMBER.match(line) for line in lines]
    if line_numbers(lines) is None:
        return lines
    rest = [line[m.end(2):] if m else line for line, m in zip(lines, found, strict=True)]
    shift = min((len(r) - len(r.lstrip()) for r in rest if r.strip()), default=0)
    return [r[shift:] for r in rest]


# None keeps the engine's text: a proportional face has no single advance, so its words would glue
def rebuild(page_glyphs: list[geometry.Glyph], box: tuple, taken: set) -> str | None:
    visible = [g for g in page_glyphs if geometry.inside(g, box)]
    if not visible or not uniform([g[2] - g[0] for g in visible]):
        return None
    advance = statistics.median(g[2] - g[0] for g in visible)
    page_rows = geometry.rows_of(page_glyphs)
    rows = []
    for middle, row in geometry.rows_of(visible):
        key = round(middle, 4)
        if all((key, round(g[0], 4)) in taken for g in row):
            continue
        # a box drawn short of the line's end cut it mid-word, so the row runs on while the line goes on
        whole = next((r for m, r in page_rows if abs(m - middle) < 1e-3), row)
        for g in whole:
            if g[0] > row[-1][0] and g[0] - row[-1][2] <= 2 * advance:
                row.append(g)
        taken.update((key, round(g[0], 4)) for g in row)
        rows.append(row)
    if not rows:
        return ""
    edge = min(row[0][0] for row in rows)
    middles = [(r[0][1] + r[0][3]) / 2 for r in rows]
    steps = sorted(b - a for a, b in zip(middles, middles[1:], strict=False))
    step = steps[(len(steps) - 1) // 2] if steps else 0
    lines = []
    for i, row in enumerate(rows):
        # a blank line has no glyphs to find, so a gap of more than one row step between rows is one or more
        if i and step > 0 and middles[i] - middles[i - 1] > 1.6 * step:
            lines += [""] * (round((middles[i] - middles[i - 1]) / step) - 1)
        line = " " * round((row[0][0] - edge) / advance)
        for before, g in zip([None, *row[:-1]], row, strict=True):
            # a space the layer's own text holds stays, though a bold glyph's box may leave it less than a cell
            if before is not None:
                line += " " * max(round((g[0] - before[2]) / advance), 1 if len(g) > 5 and g[5] else 0)
            line += g[4]
        lines.append(line.rstrip())
    return "\n".join(_without_numbers(lines))


# `glyphs` gives a file page's glyphs; a block whose box holds no monospace run keeps the engine's text
def code_from_layer(blocks: list, glyphs: Callable[[int], list]) -> tuple[list, int]:
    taken: dict[int, set] = {}
    rebuilt = 0
    out = []
    for b in blocks:
        if isinstance(b, Code) and b.where is not None:
            text = rebuild(glyphs(b.where.page), b.where.box, taken.setdefault(b.where.page, set()))
            if text == "":
                continue
            if text is not None:
                b = b.model_copy(update={"text": text})
                rebuilt += 1
        out.append(b)
    return out, rebuilt


# a fragment is cut on the left, its lines a listing's line tails; a closing `}` or `fi` is too short to tell
FRAGMENT_MIN_CHARS = 6


# a code block whose lines all stand in the overlapping code block next to it is the engine's fragment of that listing
def drop_code_fragments(blocks: list) -> tuple[list, int]:
    codes = [i for i, b in enumerate(blocks) if isinstance(b, Code) and b.where is not None]
    gone = set()
    for i, j in zip(codes, codes[1:], strict=False):
        for a, b in ((i, j), (j, i)):
            if a not in gone and b not in gone and _fragment_of(blocks[a], blocks[b]):
                gone.add(a)
    return [b for i, b in enumerate(blocks) if i not in gone], len(gone)


def _fragment_of(small: Code, whole: Code) -> bool:
    s, w = small.where, whole.where
    meet = s.box[0] < w.box[2] and w.box[0] < s.box[2] and s.box[1] < w.box[3] and w.box[1] < s.box[3]
    lines = [x.strip() for x in small.text.split("\n") if x.strip()]
    within = [x.strip() for x in whole.text.split("\n")]
    return (s.page == w.page and meet and len("".join(small.text.split())) >= FRAGMENT_MIN_CHARS
            and len(small.text) < len(whole.text) and all(any(y.endswith(x) for y in within) for x in lines))


MONO_MIN_GLYPHS = 8
# a command or a REPL line: a shell, Python, psql or a Windows prompt, or a statement closed by a semicolon
PROMPT = re.compile(r"^(?:\$|#|%|>{1,3}|=[#>]|\w+=[#>]|[A-Z]:\\)\s|;\s*$")
BULLET = re.compile(r"^[•·▪◦‣–-]\s")


# one row in one advance is a term or a name unless it reads as a command; more rows are code unless a list
def _reads_as_code(text: str, rows: int) -> bool:
    if BULLET.match(text.strip()):
        return False
    return rows > 1 or bool(PROMPT.search(text.strip()))


# a paragraph the layer sets in one advance from end to end is code an engine read as prose: a command, a snippet
def mono_paragraphs(blocks: list, glyphs: Callable[[int], list]) -> tuple[list, int]:
    out, turned = [], 0
    for b in blocks:
        if isinstance(b, Paragraph) and b.where is not None and not b.slot:
            inside = [g for g in glyphs(b.where.page) if geometry.inside(g, b.where.box)]
            if len(inside) >= MONO_MIN_GLYPHS and uniform([g[2] - g[0] for g in inside]) \
                    and _reads_as_code(b.text, len(geometry.rows_of(inside))):
                b = Code(text=b.text, where=b.where)
                turned += 1
        out.append(b)
    return out, turned


# a code box any engine drew joins the reading when the layer inside it is monospace and only prose sits there
def code_union(blocks: list, readings: list[list], glyphs: Callable[[int], list]) -> tuple[list, int]:
    out = list(blocks)
    added = 0
    for code in (b for reading in readings for b in reading if isinstance(b, Code) and b.where is not None):
        page, box = code.where.page, code.where.box
        placed = [b for b in out if not isinstance(b, PageMarker) and b.where is not None and b.where.page == page]
        if any(not isinstance(b, Paragraph) and geometry.overlap(b.where.box, box) > geometry.OVERLAP for b in placed):
            continue
        inside_glyphs = [g for g in glyphs(page) if geometry.inside(g, box)]
        if not inside_glyphs or not uniform([g[2] - g[0] for g in inside_glyphs]):
            continue
        inside = [b for b in placed if isinstance(b, Paragraph) and not b.slot and geometry.centre_in(b.where.box, box)]
        if inside:
            at = out.index(inside[0])
            out = [b for b in out if not any(b is x for x in inside)]
            out.insert(at, code)
        else:
            later = next((b for b in placed if b.where.box[1] > box[1]), None)
            out.insert(out.index(later) if later is not None else geometry.page_end(out, page), code)
        added += 1
    return out, added


PAGE_FOOT, PAGE_HEAD = 0.85, 0.2


# a code block cut by the page goes on at the top of the next one: ends low, starts high, only the page between
def join_code_across_pages(blocks: list) -> tuple[list, int]:
    out, joined = [], 0
    for b in blocks:
        if isinstance(b, Code) and b.where is not None and b.where.box[1] < PAGE_HEAD:
            between = []
            # a footnote taken back from the furniture has no place on the page, so the join looks past it
            for x in reversed(out):
                if not (isinstance(x, PageMarker) or (isinstance(x, Paragraph) and x.where is None)):
                    break
                between.append(x)
            before = out[-len(between) - 1] if between and len(out) > len(between) else None
            if (isinstance(before, Code) and before.where is not None and before.where.box[3] > PAGE_FOOT
                    and before.where.page + 1 == b.where.page):
                out[-len(between) - 1] = before.model_copy(update={"text": before.text.rstrip("\n") + "\n" + b.text})
                joined += 1
                continue
        out.append(b)
    return out, joined


# a listing's line numbers in a page of the layer, by the code pass's own test over the longest runs of rows it holds
def listing_numbers(text: str) -> Counter:
    lines = text.splitlines()
    numbers = [line_number(line) for line in lines]
    out, start = Counter(), 0
    while start < len(lines):
        best, count, last = None, 0, None
        for end in range(start, len(lines)):
            if numbers[end] is not None:
                if last is not None and numbers[end] < last:
                    break
                count, last = count + 1, numbers[end]
            size = end - start + 1
            if size >= NUMBERED_MIN_LINES and count >= NUMBERED_SHARE * size:
                best = end + 1
        found = line_numbers(lines[start:best]) if best is not None else None
        if found is None:
            start += 1
            continue
        out.update(str(n) for n in found)
        start = best
    return out
