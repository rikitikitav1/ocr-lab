# a code block's text as the text layer draws it inside the block's box: rows by height, spaces by the advance
import re
import statistics

SPREAD = 0.1
SLACK = 0.002
_NUMBER = re.compile(r"^(\s*)(\d+)(\s+)(?=\S)")

Glyph = tuple[float, float, float, float, str] | tuple[float, float, float, float, str, bool]


# glyphs of one advance as a monospace face sets them: nine in ten near the median, so a number column does not count
def uniform(widths: list[float], spread: float = SPREAD) -> bool:
    middle = statistics.median(widths) if widths else 0
    if middle <= 0:
        return False
    return sum(1 for w in widths if abs(w - middle) / middle <= spread) >= 0.9 * len(widths)


def rows_of(glyphs: list[Glyph]) -> list[tuple[float, list[Glyph]]]:
    rows: list[list] = []
    for g in sorted(glyphs, key=lambda g: (g[1] + g[3]) / 2):
        middle = (g[1] + g[3]) / 2
        if rows and abs(rows[-1][0] - middle) < (g[3] - g[1]) * 0.5:
            rows[-1][1].append(g)
        else:
            rows.append([middle, [g]])
    return [(middle, sorted(row, key=lambda g: g[0])) for middle, row in rows]


def inside(g: Glyph, box: tuple) -> bool:
    x, y = (g[0] + g[2]) / 2, (g[1] + g[3]) / 2
    return box[0] - SLACK <= x <= box[2] + SLACK and box[1] - SLACK <= y <= box[3] + SLACK


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
def rebuild(page_glyphs: list[Glyph], box: tuple, taken: set) -> str | None:
    visible = [g for g in page_glyphs if inside(g, box)]
    if not visible or not uniform([g[2] - g[0] for g in visible]):
        return None
    advance = statistics.median(g[2] - g[0] for g in visible)
    page_rows = rows_of(page_glyphs)
    rows = []
    for middle, row in rows_of(visible):
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


# the words the layer draws inside a box, rows by height and a gap of more than a third of a glyph as a space
def box_words(page_glyphs: list[Glyph], box: tuple) -> list[str]:
    text = []
    for _, row in rows_of([g for g in page_glyphs if inside(g, box)]):
        width = statistics.median(g[2] - g[0] for g in row)
        line = row[0][4]
        for before, g in zip(row, row[1:], strict=False):
            line += (" " if g[0] - before[2] > width / 3 else "") + g[4]
        text.append(line)
    return re.findall(r"\w+", " ".join(text).lower())
