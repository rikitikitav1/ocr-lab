# where a glyph or a block stands on the page: boxes, rows, overlaps; shared by the code and table elements
import re
import statistics

from document.model import PageMarker

SLACK = 0.002

Glyph = tuple[float, float, float, float, str] | tuple[float, float, float, float, str, bool]


def rows_of(glyphs: list[Glyph]) -> list[tuple[float, list[Glyph]]]:
    rows: list[list] = []
    for g in sorted(glyphs, key=lambda g: (g[1] + g[3]) / 2):
        middle = (g[1] + g[3]) / 2
        if rows and abs(rows[-1][0] - middle) < (g[3] - g[1]) * 0.5:
            rows[-1][1].append(g)
        else:
            rows.append([middle, [g]])
    return [(middle, sorted(row, key=lambda g: g[0])) for middle, row in rows]


# a glyph belongs to a box its centre falls in, with a little slack for the box's own rounding
def inside(g: Glyph, box: tuple) -> bool:
    return centre_in(g, box, SLACK)


def overlap(a: tuple, b: tuple) -> float:
    w = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    h = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    smaller = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return w * h / smaller if smaller > 0 else 0.0


OVERLAP = 0.5


def centre_in(inner, outer: tuple, slack: float = 0.0) -> bool:
    x, y = (inner[0] + inner[2]) / 2, (inner[1] + inner[3]) / 2
    return outer[0] - slack <= x <= outer[2] + slack and outer[1] - slack <= y <= outer[3] + slack


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


# each page's run of blocks, from its marker to the next one
def page_spans(blocks: list) -> list[tuple[int, int]]:
    marks = [i for i, b in enumerate(blocks) if isinstance(b, PageMarker)]
    return [(m, nxt) for m, nxt in zip(marks, [*marks[1:], len(blocks)], strict=True)]


# where a block the page holds nothing after goes: before the next page's marker, the range's end on its last page
def page_end(blocks: list, page: int) -> int:
    marker = next((i for i, b in enumerate(blocks) if isinstance(b, PageMarker) and b.file_page == page), None)
    return next((i for i, b in enumerate(blocks) if i > (marker or -1) and isinstance(b, PageMarker)), len(blocks))
