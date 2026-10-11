# the assembler's passes over a chapter's blocks; each reads only the book, never a gold
import re
import unicodedata
from collections import Counter
from collections.abc import Callable
from functools import cache

import settings
import yaml
from document.model import Code, Heading, ListBlock, PageMarker, Paragraph, Table
from rapidfuzz import fuzz

from assembly import code_layer, referee


def conf_text() -> str:
    return (settings.CONFIG_DIR / "assembly.yaml").read_text()


@cache
def conf() -> dict:
    return yaml.safe_load((settings.CONFIG_DIR / "assembly.yaml").read_text())["passes"]


# `glyphs` gives a file page's glyphs; a block whose box holds no monospace run keeps the engine's text
def code_from_layer(blocks: list, glyphs: Callable[[int], list]) -> tuple[list, int]:
    taken: dict[int, set] = {}
    rebuilt = 0
    out = []
    for b in blocks:
        if isinstance(b, Code) and b.where is not None:
            text = code_layer.rebuild(glyphs(b.where.page), b.where.box, taken.setdefault(b.where.page, set()))
            if text == "":
                continue
            if text is not None:
                b = b.model_copy(update={"text": text})
                rebuilt += 1
        out.append(b)
    return out, rebuilt


def _overlap(a: tuple, b: tuple) -> float:
    w = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    h = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    smaller = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return w * h / smaller if smaller > 0 else 0.0


OVERLAP = 0.5


def _agreement(table: Table, layer: Counter) -> float:
    return referee.f1(layer, Counter(re.findall(r"\w+", " ".join(c.text for row in table.rows for c in row).lower())))


# a layer glyph can read as several characters (a ligature), so each one is looked at
def is_mark(ch: str) -> bool:
    return any(unicodedata.category(c) in ("So", "Sm") or c in "•·▪◦‣" for c in ch)


def _marks_kept(table: Table, page: list) -> int:
    layer = sum(is_mark(g[4]) for g in page if code_layer.inside(g, table.where.box))
    return min(layer, sum(is_mark(ch) for row in table.rows for c in row for ch in c.text))


# a table takes the grid whose cells agree better with the layer words in its box; a tie goes to the preferred engine
def tables_by_layer(blocks: list, preferred: list, glyphs: Callable[[int], list]) -> tuple[list, int]:
    theirs = [b for b in preferred if isinstance(b, Table) and b.where is not None]
    engine = theirs[0].where.engine if theirs else None
    out, swapped = [], 0
    for b in blocks:
        if isinstance(b, Table) and b.where is not None and b.where.engine != engine:
            same = [t for t in theirs if t.where.page == b.where.page and _overlap(t.where.box, b.where.box) > OVERLAP]
            if len(same) == 1:
                page = glyphs(b.where.page)
                mine = Counter(code_layer.box_words(page, b.where.box))
                other = Counter(code_layer.box_words(page, same[0].where.box))
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
            same = [t for t in theirs if t.where.page == b.where.page and _overlap(t.where.box, b.where.box) > OVERLAP]
            if len(same) == 1:
                b = same[0]
                swapped += 1
        out.append(b)
    return out, swapped


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
        if isinstance(b, Paragraph) and b.where is not None:
            inside = [g for g in glyphs(b.where.page) if code_layer.inside(g, b.where.box)]
            if len(inside) >= MONO_MIN_GLYPHS and code_layer.uniform([g[2] - g[0] for g in inside]) \
                    and _reads_as_code(b.text, len(code_layer.rows_of(inside))):
                b = Code(text=b.text, where=b.where)
                turned += 1
        out.append(b)
    return out, turned


def _centre_in(inner, outer: tuple) -> bool:
    x, y = (inner[0] + inner[2]) / 2, (inner[1] + inner[3]) / 2
    return outer[0] <= x <= outer[2] and outer[1] <= y <= outer[3]


# a code box any engine drew joins the reading when the layer inside it is monospace and only prose sits there
def code_union(blocks: list, readings: list[list], glyphs: Callable[[int], list]) -> tuple[list, int]:
    out = list(blocks)
    added = 0
    for code in (b for reading in readings for b in reading if isinstance(b, Code) and b.where is not None):
        page, box = code.where.page, code.where.box
        placed = [b for b in out if not isinstance(b, PageMarker) and b.where is not None and b.where.page == page]
        if any(not isinstance(b, Paragraph) and _overlap(b.where.box, box) > OVERLAP for b in placed):
            continue
        inside_glyphs = [g for g in glyphs(page) if code_layer.inside(g, box)]
        if not inside_glyphs or not code_layer.uniform([g[2] - g[0] for g in inside_glyphs]):
            continue
        inside = [b for b in placed if isinstance(b, Paragraph) and _centre_in(b.where.box, box)]
        if inside:
            at = out.index(inside[0])
            out = [b for b in out if not any(b is x for x in inside)]
            out.insert(at, code)
        else:
            later = next((b for b in placed if b.where.box[1] > box[1]), None)
            if later is not None:
                out.insert(out.index(later), code)
            else:
                marker = next((i for i, b in enumerate(out) if isinstance(b, PageMarker) and b.file_page == page), None)
                nxt = next((i for i, b in enumerate(out) if i > (marker or -1) and isinstance(b, PageMarker)), len(out))
                out.insert(nxt, code)
        added += 1
    return out, added


TABLE_UNION_AGREEMENT = 0.8


# a table only the other engine drew joins the reading when its cells agree with the layer in its box; prose gives way
def table_union(blocks: list, preferred: list, glyphs: Callable[[int], list]) -> tuple[list, int]:
    out, added = list(blocks), 0
    for table in (b for b in preferred if isinstance(b, Table) and b.where is not None):
        page, box = table.where.page, table.where.box
        placed = [b for b in out if not isinstance(b, PageMarker) and b.where is not None and b.where.page == page]
        if any(isinstance(b, Table) and _overlap(b.where.box, box) > OVERLAP for b in placed):
            continue
        layer = Counter(code_layer.box_words(glyphs(page), box))
        if _agreement(table, layer) < TABLE_UNION_AGREEMENT:
            continue
        inside = [b for b in placed if _centre_in(b.where.box, box)]
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


PAGE_FOOT, PAGE_HEAD = 0.85, 0.2


# a code block cut by the page goes on at the top of the next one: ends low, starts high, only the page between
def join_code_across_pages(blocks: list) -> tuple[list, int]:
    out, joined = [], 0
    for b in blocks:
        if isinstance(b, Code) and b.where is not None and b.where.box[1] < PAGE_HEAD:
            between = []
            for x in reversed(out):
                if not isinstance(x, PageMarker):
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


# the passes in order over one file range; `steps` gets each pass's blocks, `picks` the referee's choice per page
def apply(reads: dict, layer: dict[int, str], glyphs: Callable[[int], list],
          order: tuple[str, ...], steps: list | None = None, knobs: dict | None = None,
          picks: dict | None = None) -> tuple[list, dict]:
    on = {**conf(), **(knobs or {})}
    blocks, picked = referee.per_page({e: r.blocks for e, r in reads.items()}, layer, order)
    if picks is not None:
        picks.update(picked)
    steps = [] if steps is None else steps
    steps.append(("referee", blocks))
    counts: dict = {}
    for page in picked.values():
        counts[f"pages_{page['picked']}"] = counts.get(f"pages_{page['picked']}", 0) + 1
    if preferred := on.get("tables_from"):
        if on.get("tables_by") == "layer":
            blocks, counts["tables_swapped"] = tables_by_layer(blocks, reads[preferred].blocks, glyphs)
        else:
            blocks, counts["tables_swapped"] = tables_from(blocks, reads[preferred].blocks)
        steps.append(("tables", blocks))
    if on.get("table_union") and preferred:
        blocks, counts["tables_added"] = table_union(blocks, reads[preferred].blocks, glyphs)
        steps.append(("table_union", blocks))
    if on.get("code_union"):
        blocks, counts["code_added"] = code_union(blocks, [r.blocks for r in reads.values()], glyphs)
        steps.append(("code_union", blocks))
    if on.get("mono_paragraphs"):
        blocks, counts["paragraphs_to_code"] = mono_paragraphs(blocks, glyphs)
        steps.append(("mono_paragraphs", blocks))
    if on.get("code_from_layer"):
        blocks, counts["code_rebuilt"] = code_from_layer(blocks, glyphs)
        steps.append(("code_from_layer", blocks))
    if on.get("join_code_across_pages"):
        blocks, counts["code_joined"] = join_code_across_pages(blocks)
        steps.append(("join_code_across_pages", blocks))
    return blocks, counts


SUB_ENTRY_SIMILARITY = 90


# a heading and a toc title are one when they read alike, spacing and case aside, or alike with no space at all
def same_title(a: str, b: str) -> bool:
    if fuzz.WRatio(" ".join(a.split()).lower(), " ".join(b.split()).lower()) >= SUB_ENTRY_SIMILARITY:
        return True
    return fuzz.ratio("".join(a.split()).lower(), "".join(b.split()).lower()) >= SUB_ENTRY_SIMILARITY
MAX_LEVEL = 6


# the chapter's own title set again on its first page is the writer's heading already, so it goes
def without_title(blocks: list, title: str) -> tuple[list, int]:
    first = next((i for i, b in enumerate(blocks) if not isinstance(b, PageMarker)), None)
    if first is not None and isinstance(blocks[first], Heading) and same_title(blocks[first].text, title):
        return blocks[:first] + blocks[first + 1:], 1
    return blocks, 0


def _page_spans(blocks: list) -> list[tuple[int, int]]:
    marks = [i for i, b in enumerate(blocks) if isinstance(b, PageMarker)]
    return [(m, nxt) for m, nxt in zip(marks, [*marks[1:], len(blocks)], strict=True)]


def _titled(blocks: list, start: int, end: int, title: str) -> int | None:
    def text(i: int) -> str:
        return " ".join(referee.block_text(blocks[i]).split())

    # a title is a short block: a paragraph only contains the title's words, and WRatio would take it on a part
    short = [i for i in range(start, end) if not isinstance(blocks[i], PageMarker)
             and len(text(i).split()) <= 2 * len(title.split()) + 2]
    found = [i for i in short if same_title(text(i), title)]
    # "Раздел I" reads alike to "Раздел II", so a block written exactly as the title wins over a near one
    exact = [i for i in found if text(i).lower() == " ".join(title.split()).lower()]
    return (exact or found or [None])[0]


# on a page two chapters share, before a chapter's own title and from the next one's title on is not its text
def shared_pages(blocks: list, title: str, shared_start: bool, next_title: str | None) -> tuple[list, dict]:
    counts = {"shared_cut_blocks": 0, "shared_title_missing": 0, "shared_cut_start": 0, "shared_cut_end": 0}
    spans = _page_spans(blocks)
    if not spans:
        return blocks, counts
    drop: set[int] = set()
    own = None
    # a chapter that starts on its last page seeks its own title there too, so the next title is sought after it
    if shared_start or (next_title and len(spans) == 1):
        start, end = spans[0]
        own = _titled(blocks, start + 1, end, title)
    if shared_start:
        if own is None:
            counts["shared_title_missing"] += 1
        else:
            drop.update(range(spans[0][0] + 1, own))
            counts["shared_cut_start"] = 1
    if next_title:
        start, end = spans[-1]
        after = start + 1 if own is None or own < start else own + 1
        nxt = _titled(blocks, after, end, next_title)
        if nxt is None:
            counts["shared_title_missing"] += 1
        else:
            drop.update(range(nxt, end))
            counts["shared_cut_end"] = 1
    counts["shared_cut_blocks"] = len(drop)
    return [b for i, b in enumerate(blocks) if i not in drop], counts


# a toc sub-entry gives its level, the rest keep the engine's order from 1; past the ceiling demoted and counted
def chapter_levels(blocks: list, toc_level: int, subs: list[tuple[str, int]]) -> tuple[list, dict]:
    ceiling = MAX_LEVEL - (toc_level + 1)
    heads = [b for b in blocks if isinstance(b, Heading)]
    top = min((h.level for h in heads), default=1)
    counts = {"headings_from_toc": 0, "headings_demoted": 0, "headings_flattened": 0}
    out = []
    for b in blocks:
        # a chapter at the deepest level leaves no level for headings inside it: they stay as paragraphs
        if isinstance(b, Heading) and ceiling < 1:
            counts["headings_flattened"] += 1
            b = Paragraph(text=b.text, where=b.where)
        elif isinstance(b, Heading):
            sub = next((lvl for title, lvl in subs if same_title(b.text, title)), None)
            if sub is not None:
                level, source = max(1, sub - toc_level), "toc"
                counts["headings_from_toc"] += 1
            else:
                level, source = b.level - top + 1, b.level_source
            if level > ceiling:
                counts["headings_demoted"] += 1
                level = ceiling
            b = b.model_copy(update={"level": min(level, 5), "level_source": source})
        out.append(b)
    return out, counts


# recognised pages have no layer to judge by: the text is one engine's, the two engines' word agreement is the measure
def recognised(reads: dict, prefer: str, steps: list | None = None,
               min_words: int = 0) -> tuple[list, dict, dict[int, float]]:
    pages = {e: referee.by_page(r.blocks) for e, r in reads.items()}
    other = next(e for e in reads if e != prefer)
    agreement, pictures = {}, 0
    for page in pages[prefer]:
        words = {e: Counter(referee.WORD.findall(" ".join(referee.block_text(b) for b in pages[e].get(page, []))
                                                 .lower())) for e in (prefer, other)}
        # a plate's caption against nothing is no measure of recognition; one engine failing alone is not a plate
        if max(sum(w.values()) for w in words.values()) < min_words:
            pictures += 1
            continue
        agreement[page] = round(referee.f1(words[prefer], words[other]), 3)
    blocks = reads[prefer].blocks
    if steps is not None:
        steps.append(("recognised", blocks))
    return blocks, {"pages_recognised": len(agreement), "pages_picture": pictures}, agreement
