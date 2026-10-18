# a picture's caption by the text layer alone: the block just under or over the picture, set apart from the body by size
from assembly import caption_series as series

MAX_WORDS = 60


# the caption's reach from its picture and the rows it runs on over are the book's caption series' own
def _caption(box: tuple, lines: list, body: float) -> str | None:
    x0, y0, x1, y1 = box
    beside = [x for x in lines if x0 - 20 <= x.x <= x1]
    below = sorted((x for x in beside if y1 - 2 <= x.top <= y1 + series.BY_DRAWING), key=lambda x: x.top)
    above = sorted((x for x in beside if y0 - series.BY_DRAWING <= x.top + x.size <= y0 + 2), key=lambda x: x.top)
    if below:
        found = _apart(series.rows(below[0], lines), body)
        if found:
            return found
    return _apart(above[-1:], body) if above else None


# a caption's rows are set apart from the body the way the caption series' own lines are
def _apart(run: list, body: float) -> str | None:
    text = " ".join(x.text for x in run)
    return text if len(text.split()) <= MAX_WORDS and series.apart(run[0], body) else None


# captions by book page, from the pictures on each page and the layer's lines there
def by_page(pictures: dict[int, list[tuple]], lines: dict[int, list]) -> dict[int, list[str]]:
    body = series.body_size(lines)
    out = {}
    for page, boxes in pictures.items():
        found = [c for c in (_caption(box, lines.get(page, []), body) for box in boxes) if c]
        if found:
            out[page] = found
    return out
