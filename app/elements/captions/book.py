# the caption element, learned from the book: the numbered series its lines set apart, a picture's caption
import re
import statistics
from collections import defaultdict
from collections.abc import Callable

LABEL = re.compile(r"^([^\W\d_]{2,}\.?)\s*(\d+(?:[.\-–:]\d+)*)[.:]?(\s|$)")


# a contents or list line ends in its page number
PAGE_TAIL = re.compile(r"[\s.·…_]{2,}\d+\s*$|\s\d+\s*$")


MIN_LINES = 5


MIN_WORDS = 3


RISING = 0.8


# a series is the book's captions when half its lines or more stand by a picture or a drawing
WITH_NEIGHBOUR = 0.5


# a caption stands this close above or below a picture or a drawn diagram, in points, and overlaps it across
BY_DRAWING = 30.0


# a caption runs on over rows of its own size, no further apart than this, at most this many rows
ROW_GAP = 1.6


MAX_ROWS = 3


# a page holding this many series lines and no neighbour by any is a list of figures, not captions
LIST_LINES = 3


def _number(text: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.split(r"[.\-–:]", text) if n)


# the body's size: the median of the sizes the layer sets, a line with no size left out
def body_size(lines: dict[int, list]) -> float:
    sizes = [ln.size for ls in lines.values() for ln in ls if ln.size]
    return statistics.median(sizes) if sizes else 0.0


# a caption is set apart from the body by its first word's size or weight, or by its own size
def apart(line, body: float) -> bool:
    return abs(line.head_size - body) > 0.05 * body or line.head_bold or abs(line.size - body) > 0.05 * body


def _overlaps(a, b) -> bool:
    return a.x < max(b.right, b.x + 1) and b.x < max(a.right, a.x + 1)


def _by_drawing(line, drawings: list) -> bool:
    bottom = line.top + (line.size or 0)
    return any(d[0] - 20 < max(line.right, line.x + 1) and line.x < d[2] + 20
               and (abs(line.top - d[3]) < BY_DRAWING or abs(d[1] - bottom) < BY_DRAWING) for d in drawings)


def _plain(text: str) -> str:
    return " ".join(PAGE_TAIL.sub("", text).split()).casefold()


# a caption with the rows it runs on over: its own size, close below it, a few at most, up to the next caption
def rows(line, page_lines: list) -> list:
    rows = [line]
    for o in sorted((o for o in page_lines if o.top > line.top and _overlaps(o, line)), key=lambda o: o.top):
        if len(rows) >= MAX_ROWS or o.top - rows[-1].top > ROW_GAP * (rows[-1].size or 1) or o.size != line.size \
                or LABEL.match(o.text):
            break
        rows.append(o)
    return rows


# each page's caption texts, a caption's rows joined; empty when the book prints no numbered series by its pictures
def learn(lines: dict[int, list], titles: frozenset[str] = frozenset(),
          drawings: Callable[[int], list] = lambda page: []) -> dict[int, list[str]]:
    body = body_size(lines)
    if not body:
        return {}
    series: dict[str, list[tuple[int, object, tuple[int, ...]]]] = defaultdict(list)
    for page, ls in sorted(lines.items()):
        for ln in ls:
            m = LABEL.match(ln.text)
            if m and len(ln.text.split()) >= MIN_WORDS and not PAGE_TAIL.search(ln.text) and apart(ln, body):
                series[m.group(1).rstrip(".").casefold()].append((page, ln, _number(m.group(2))))
    out: dict[int, list[str]] = defaultdict(list)
    heads = {_plain(t) for t in titles}
    for found in series.values():
        # a numbered structure heading ("Chapter 2: Components") is a node of the book, not a caption
        named = [f for f in found if _plain(f[1].text) in heads]
        if len(named) >= WITH_NEIGHBOUR * len(found):
            continue
        found = [f for f in found if f not in named]
        numbers = [n for _, _, n in found]
        if len(found) < MIN_LINES or len(set(numbers)) < RISING * len(numbers):
            continue
        rising = sum(a <= b for a, b in zip(numbers, numbers[1:], strict=False))
        if rising < RISING * (len(numbers) - 1):
            continue
        near = [(page, ln, _by_drawing(ln, drawings(page))) for page, ln, _ in found]
        if sum(n for _, _, n in near) < WITH_NEIGHBOUR * len(near):
            continue
        by_page: dict[int, list] = defaultdict(list)
        for page, ln, n in near:
            by_page[page].append((ln, n))
        for page, got in by_page.items():
            if len(got) >= LIST_LINES and not any(n for _, n in got):
                continue
            out[page] += [" ".join(r.text for r in rows(ln, lines[page])) for ln, _ in got]
    return dict(out)


MAX_WORDS = 60


# the caption's reach from its picture and the rows it runs on over are the book's caption series' own
def _caption(box: tuple, lines: list, body: float) -> str | None:
    x0, y0, x1, y1 = box
    beside = [x for x in lines if x0 - 20 <= x.x <= x1]
    below = sorted((x for x in beside if y1 - 2 <= x.top <= y1 + BY_DRAWING), key=lambda x: x.top)
    above = sorted((x for x in beside if y0 - BY_DRAWING <= x.top + x.size <= y0 + 2), key=lambda x: x.top)
    if below:
        found = _apart(rows(below[0], lines), body)
        if found:
            return found
    return _apart(above[-1:], body) if above else None


# a caption's rows are set apart from the body the way the caption series' own lines are
def _apart(run: list, body: float) -> str | None:
    text = " ".join(x.text for x in run)
    return text if len(text.split()) <= MAX_WORDS and apart(run[0], body) else None


# captions by book page, from the pictures on each page and the layer's lines there
def by_page(pictures: dict[int, list[tuple]], lines: dict[int, list]) -> dict[int, list[str]]:
    body = body_size(lines)
    out = {}
    for page, boxes in pictures.items():
        found = [c for c in (_caption(box, lines.get(page, []), body) for box in boxes) if c]
        if found:
            out[page] = found
    return out
