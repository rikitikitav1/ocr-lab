# the table element: whose grid a table takes, by the layer's words and marks in its box; tables one engine alone drew
import re
import unicodedata
from collections import Counter
from collections.abc import Callable

from assembly import referee
from document.model import Heading, ListBlock, PageMarker, Paragraph, Table

from elements import geometry


def _agreement(table: Table, layer: Counter) -> float:
    return referee.f1(layer, Counter(re.findall(r"\w+", " ".join(c.text for row in table.rows for c in row).lower())))


# a layer glyph can read as several characters (a ligature), so each one is looked at
def is_mark(ch: str) -> bool:
    return any(unicodedata.category(c) in ("So", "Sm") or c in "•·▪◦‣" for c in ch)


def _marks_kept(table: Table, page: list) -> int:
    layer = sum(is_mark(g[4]) for g in page if geometry.inside(g, table.where.box))
    return min(layer, sum(is_mark(ch) for row in table.rows for c in row for ch in c.text))


# a table takes the grid whose cells agree better with the layer words in its box; a tie goes to the preferred engine
def tables_by_layer(blocks: list, preferred: list, glyphs: Callable[[int], list]) -> tuple[list, int]:
    theirs = [b for b in preferred if isinstance(b, Table) and b.where is not None]
    engine = theirs[0].where.engine if theirs else None
    out, swapped = [], 0
    for b in blocks:
        if isinstance(b, Table) and b.where is not None and b.where.engine != engine:
            same = [t for t in theirs if t.where.page == b.where.page
                    and geometry.overlap(t.where.box, b.where.box) > geometry.OVERLAP]
            if len(same) == 1:
                page = glyphs(b.where.page)
                mine = Counter(geometry.box_words(page, b.where.box))
                other = Counter(geometry.box_words(page, same[0].where.box))
                # marks first (a grid dropping the layer's check marks loses), then words, each in its own box
                kept = _marks_kept(same[0], page), _marks_kept(b, page)
                if kept[0] > kept[1] or (kept[0] == kept[1] and _agreement(same[0], other) >= _agreement(b, mine)):
                    b = same[0]
                    swapped += 1
        out.append(b)
    return out, swapped


# a table takes the preferred engine's grid at the same place, unless that engine split the place into pieces
def tables_from(blocks: list, preferred: list) -> tuple[list, int]:
    theirs = [b for b in preferred if isinstance(b, Table) and b.where is not None]
    engine = theirs[0].where.engine if theirs else None
    out, swapped = [], 0
    for b in blocks:
        if isinstance(b, Table) and b.where is not None and b.where.engine != engine:
            same = [t for t in theirs if t.where.page == b.where.page
                    and geometry.overlap(t.where.box, b.where.box) > geometry.OVERLAP]
            if len(same) == 1:
                b = same[0]
                swapped += 1
        out.append(b)
    return out, swapped


TABLE_UNION_AGREEMENT = 0.8


# a table only the other engine drew joins the reading when its cells agree with the layer in its box; prose gives way
def table_union(blocks: list, preferred: list, glyphs: Callable[[int], list]) -> tuple[list, int]:
    out, added = list(blocks), 0
    for table in (b for b in preferred if isinstance(b, Table) and b.where is not None):
        page, box = table.where.page, table.where.box
        placed = [b for b in out if not isinstance(b, PageMarker) and b.where is not None and b.where.page == page]
        if any(isinstance(b, Table) and geometry.overlap(b.where.box, box) > geometry.OVERLAP for b in placed):
            continue
        layer = Counter(geometry.box_words(glyphs(page), box))
        if _agreement(table, layer) < TABLE_UNION_AGREEMENT:
            continue
        inside = [b for b in placed if geometry.centre_in(b.where.box, box)]
        if any(not isinstance(b, (Paragraph, ListBlock, Heading)) for b in inside):
            continue
        if inside:
            at = out.index(inside[0])
            out = [b for b in out if not any(b is x for x in inside)]
        else:
            later = next((b for b in placed if b.where.box[1] > box[1]), None)
            at = out.index(later) if later is not None else len(out)
        out.insert(at, table)
        added += 1
    return out, added
