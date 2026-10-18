# the assembler's passes over a piece's blocks; each reads only the book, never a gold
import re
import unicodedata
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from functools import cache

import numerals
import settings
import yaml
from document.model import Caption, Code, Contents, Figure, Heading, ListBlock, PageMarker, Paragraph, Table
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
        if isinstance(b, Paragraph) and b.where is not None and not b.slot:
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
        inside = [b for b in placed if isinstance(b, Paragraph) and not b.slot and _centre_in(b.where.box, box)]
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


# a page two pieces meet on: the next piece's title, and which side this piece takes of it
@dataclass(frozen=True)
class Boundary:
    page: int
    title: str
    tail: bool


def _norm(text: str) -> str:
    return " ".join(text.split()).casefold()


# a block whose whole text is a slot line its page layout claims, or its page's claimed lines run together, is marked
def mark_slots(blocks: list, slots: dict[int, list[tuple[str, str, float]]],
               parts: bool = False) -> tuple[list, int]:
    out, n, here = [], 0, {}
    for b in blocks:
        if isinstance(b, PageMarker):
            lines = slots.get(b.file_page, [])
            here = {_norm(t): r for t, r, *_ in lines}
            if len(lines) > 1:
                here.setdefault(_norm(" ".join(t for t, *_ in lines)), lines[0][1])
        elif here and isinstance(b, (Heading, Paragraph, Caption)) and _norm(b.text) in here:
            b = b.model_copy(update={"slot": here[_norm(b.text)]})
            n += 1
        elif here and isinstance(b, ListBlock) and any(_norm(i.text) in here for i in b.items):
            items = [i.model_copy(update={"slot": here[_norm(i.text)]}) if _norm(i.text) in here else i
                     for i in b.items]
            n += sum(i.slot is not None for i in items)
            b = b.model_copy(update={"items": items})
        out.append(b)
    if parts:
        out, more = _mark_parts(out, slots)
        n += more
    return out, n


SLOT_BAND = 0.04


# blocks of one page standing in a claimed line's band whose words, together, are that line word for word
def _mark_parts(blocks: list, slots: dict[int, list[tuple[str, str, float]]]) -> tuple[list, int]:
    out, n, page = list(blocks), 0, None
    by_page: dict[int, list[int]] = {}
    for k, b in enumerate(out):
        if isinstance(b, PageMarker):
            page = b.file_page
        elif page is not None and isinstance(b, (Heading, Paragraph, Caption)) and not b.slot and b.where:
            by_page.setdefault(page, []).append(k)
    for page, ks in by_page.items():
        for text, reason, top in slots.get(page, []):
            words = _norm(text).split()
            near = [k for k in ks if not out[k].slot and abs(out[k].where.box[1] - top) <= SLOT_BAND]
            spans = [(k, _span(words, _norm(out[k].text).split())) for k in near]
            spans = [(k, s) for k, s in spans if s is not None and s[1] - s[0] < len(words)]
            covered = sorted(s for _, s in spans)
            if len(covered) < 2 or covered[0][0] != 0 or covered[-1][1] != len(words) or \
                    any(a[1] != b[0] for a, b in zip(covered, covered[1:], strict=False)):
                continue
            for k, _ in spans:
                out[k] = out[k].model_copy(update={"slot": reason})
                n += 1
    return out, n


# where a block's words stand inside a line's words, at word boundaries, once
def _span(line: list[str], block: list[str]) -> tuple[int, int] | None:
    found = [i for i in range(len(line) - len(block) + 1) if block and line[i:i + len(block)] == block]
    return (found[0], found[0] + len(block)) if len(found) == 1 else None


NOTE_HEAD_WORDS = 6
NOTE_MIN_WORDS = 3


# a footnote an engine set aside as furniture comes back at its page's end when the page layout reads it as a note
def notes_from_furniture(blocks: list, reads: dict, picked: dict, notes: dict[int, str]) -> tuple[list, int]:
    back: dict[int, list[Paragraph]] = {}
    for page, pick in picked.items():
        if page not in notes:
            continue
        for at, _, text in getattr(reads[pick["picked"]], "furniture_at", []):
            words = _norm(text).split()
            if at == page and len(words) >= NOTE_MIN_WORDS and f" {' '.join(words[:NOTE_HEAD_WORDS])} " in notes[page]:
                back.setdefault(page, []).append(Paragraph(text=" ".join(text.split())))
    if not back:
        return blocks, 0
    out, page = [], None
    for b in blocks:
        if isinstance(b, PageMarker):
            out += back.get(page, [])
            page = b.file_page
        out.append(b)
    out += back.get(page, [])
    return out, sum(map(len, back.values()))


# a caption of the book's series an engine set aside as furniture comes back after the picture, table or listing
def captions_from_furniture(blocks: list, reads: dict, picked: dict,
                            captions: dict[int, list[str]]) -> tuple[list, int]:
    book_page = {b.file_page: b.book_page for b in blocks if isinstance(b, PageMarker)}
    back: dict[int, list[Caption]] = {}
    for page, pick in picked.items():
        wanted = captions.get(book_page.get(page), [])
        for at, _, text in getattr(reads[pick["picked"]], "furniture_at", []) if wanted else []:
            if at == page and any(_caption_cut(text, w) is not None for w in wanted):
                back.setdefault(page, []).append(Caption(text=" ".join(text.split())))
    out, page, n = [], None, 0
    for b in blocks:
        if isinstance(b, PageMarker):
            page = b.file_page
        out.append(b)
        if back.get(page) and isinstance(b, (Figure, Table, Code)):
            out.append(back[page].pop(0))
            n += 1
    return out, n


# marked blocks go, but a heading a node opens at stays: a chapter's title is often its own running head
def drop_slots(blocks: list) -> tuple[list, int]:
    out, n = [], 0
    for b in blocks:
        if getattr(b, "slot", None) and not (isinstance(b, Heading) and b.node is not None):
            n += 1
            continue
        if isinstance(b, ListBlock) and any(i.slot for i in b.items):
            items = [i for i in b.items if not i.slot]
            n += len(b.items) - len(items)
            if not items:
                continue
            b = b.model_copy(update={"items": items})
        out.append(b)
    return out, n


# an engine block holding a row the layer reader joined takes it joined, the engine having read the same spaced glyphs
def respaced(blocks: list, rows: dict[int, list[tuple[str, str]]]) -> tuple[list, int]:
    out, n, here = [], 0, []
    for b in blocks:
        if isinstance(b, PageMarker):
            here = [(_spacing(r), j) for r, j in rows.get(b.file_page, []) if r != j]
        elif here and isinstance(b, (Heading, Paragraph, Caption)):
            text = _spacing(b.text)
            for _, joined in here:
                text = _take(text, joined)
            if text != _spacing(b.text):
                b = b.model_copy(update={"text": text})
                n += 1
        out.append(b)
    return out, n


def _spacing(text: str) -> str:
    return " ".join(text.split())


# the block's span holding the row's letters becomes the row as joined, when that only takes spaces out of the span
def _take(text: str, joined: str) -> str:
    at = [i for i, c in enumerate(text) if not c.isspace()]
    letters, want = "".join(text[i] for i in at), "".join(joined.split())
    k = letters.find(want) if want else -1
    if k < 0:
        return text
    a, b = at[k], at[k + len(want) - 1] + 1
    return text[:a] + _spacing(joined) + text[b:] if _gaps(joined) < _gaps(text[a:b]) else text


# the letters a space follows, counted by letter, so two spellings of one row can be compared
def _gaps(text: str) -> set[int]:
    out, n = set(), 0
    for c in text:
        if c.isspace():
            out.add(n)
        else:
            n += 1
    return out


# the passes in order over one file range; `steps` gets each pass's blocks, `picks` the referee's choice per page
def apply(reads: dict, layer: dict[int, str], glyphs: Callable[[int], list],
          order: tuple[str, ...], steps: list | None = None, knobs: dict | None = None,
          picks: dict | None = None, boundaries: list[Boundary] = (),
          records: list | None = None, slots: dict | None = None,
          joined_rows: dict | None = None, notes: dict[int, str] | None = None,
          captions: dict[int, list[str]] | None = None) -> tuple[list, dict]:
    on = {**conf(), **(knobs or {})}
    blocks, picked = referee.per_page({e: r.blocks for e, r in reads.items()}, layer, order)
    if picks is not None:
        picks.update(picked)
    steps = [] if steps is None else steps
    steps.append(("referee", blocks))
    counts: dict = {}
    if notes and on.get("notes_from_furniture"):
        blocks, counts["notes_from_furniture"] = notes_from_furniture(blocks, reads, picked, notes)
        steps.append(("notes_from_furniture", blocks))
    if captions and on.get("caption_series"):
        blocks, counts["captions_from_furniture"] = captions_from_furniture(blocks, reads, picked, captions)
        steps.append(("captions_from_furniture", blocks))
    # an engine's spaced row is joined before the slots are matched, since the layout reads its lines joined
    if joined_rows:
        blocks, counts["rows_respaced"] = respaced(blocks, joined_rows)
        steps.append(("respaced", blocks))
    # slots are marked first, so a boundary's tail, the earlier piece's own text, leaves its running head out
    if slots:
        blocks, counts["slot_marked"] = mark_slots(blocks, slots, bool(on.get("slot_parts")))
    # the boundary pages are cut before any pass, so no pass works on the neighbour's half
    blocks, others, cut = cut_boundaries(blocks, {e: r.blocks for e, r in reads.items()}, list(boundaries))
    if records is not None:
        records += cut
    for page in picked.values():
        counts[f"pages_{page['picked']}"] = counts.get(f"pages_{page['picked']}", 0) + 1
    if preferred := on.get("tables_from"):
        if on.get("tables_by") == "layer":
            blocks, counts["tables_swapped"] = tables_by_layer(blocks, others[preferred], glyphs)
        else:
            blocks, counts["tables_swapped"] = tables_from(blocks, others[preferred])
        steps.append(("tables", blocks))
    if on.get("table_union") and preferred:
        blocks, counts["tables_added"] = table_union(blocks, others[preferred], glyphs)
        steps.append(("table_union", blocks))
    if on.get("code_union"):
        blocks, counts["code_added"] = code_union(blocks, list(others.values()), glyphs)
        steps.append(("code_union", blocks))
    if on.get("mono_paragraphs"):
        blocks, counts["paragraphs_to_code"] = mono_paragraphs(blocks, glyphs)
        steps.append(("mono_paragraphs", blocks))
    if on.get("code_from_layer"):
        blocks, counts["code_rebuilt"] = code_from_layer(blocks, glyphs)
        blocks, counts["code_fragments"] = drop_code_fragments(blocks)
        steps.append(("code_from_layer", blocks))
    if on.get("join_code_across_pages"):
        blocks, counts["code_joined"] = join_code_across_pages(blocks)
        steps.append(("join_code_across_pages", blocks))
    return blocks, counts


SUB_ENTRY_SIMILARITY = 90


# a heading and a structure title are one when they read alike, spacing and case aside, or alike with no space at all
def same_title(a: str, b: str) -> bool:
    if fuzz.WRatio(" ".join(a.split()).lower(), " ".join(b.split()).lower()) >= SUB_ENTRY_SIMILARITY:
        return True
    return fuzz.ratio("".join(a.split()).lower(), "".join(b.split()).lower()) >= SUB_ENTRY_SIMILARITY
MAX_LEVEL = 6


# the piece's own title set again on its first page is the writer's heading already, so it goes
def without_title(blocks: list, title: str) -> tuple[list, int]:
    # the title's label set over it ("Chapter 1") stays as the book's text, the title the writer sets goes
    first = next((i for i, b in enumerate(blocks) if not isinstance(b, PageMarker)
                  and not (_label(b) and not same_title(referee.block_text(b), title))), None)
    if first is not None and isinstance(blocks[first], Heading) and same_title(blocks[first].text, title):
        return blocks[:first] + blocks[first + 1:], 1
    return blocks, 0


def _page_spans(blocks: list) -> list[tuple[int, int]]:
    marks = [i for i, b in enumerate(blocks) if isinstance(b, PageMarker)]
    return [(m, nxt) for m, nxt in zip(marks, [*marks[1:], len(blocks)], strict=True)]


def titled(blocks: list, start: int, end: int, title: str) -> int | None:
    def text(i: int) -> str:
        return " ".join(referee.block_text(blocks[i]).split())

    # a title is a short block: a paragraph only contains the title's words, and WRatio would take it on a part
    short = [i for i in range(start, end) if not isinstance(blocks[i], PageMarker)
             and len(text(i).split()) <= 2 * len(title.split()) + 2]
    found = [i for i in short if same_title(text(i), title)]
    # "Раздел I" reads alike to "Раздел II", so a block written exactly as the title wins over a near one
    exact = [i for i in found if text(i).lower() == " ".join(title.split()).lower()]
    return (exact or found or [None])[0]


LOOSE_TITLE = 85
LOOSE_SHARE = 0.4


# a title with its label glued on ("Scope of the studyC.") or run into the next row, on letters alone, a fair share long
def titled_loosely(blocks: list, start: int, end: int, title: str) -> int | None:
    def squashed(s: str) -> str:
        return "".join(ch for ch in s.lower() if ch.isalnum())

    want = squashed(title)
    best, at = 0.0, None
    for i in range(start, end):
        if isinstance(blocks[i], PageMarker):
            continue
        text = referee.block_text(blocks[i])
        got = squashed(text)
        if len(text.split()) > 2 * len(title.split()) + 2 or len(got) < LOOSE_SHARE * len(want):
            continue
        # the match must start the block, or a cross-reference ("See the X-Case, p. 323") passes for the title
        fit = fuzz.partial_ratio_alignment(got, want)
        if fit.src_start == 0 and fit.score >= LOOSE_TITLE and fit.score > best:
            best, at = fit.score, i
    return at


# a unit's own title read on its first page, the head's pin as an inner node's is its matched heading
def title_on_first_page(blocks: list, title: str) -> bool:
    spans = _page_spans(blocks)
    return bool(spans) and titled(blocks, spans[0][0] + 1, spans[0][1], title) is not None


# on a page two pieces share, before a piece's own title and from the next one's title on is not its text
def _top(block) -> float | None:
    where = getattr(block, "where", None)
    return where.box[1] if where is not None else None


# blocks read before a title and set above it: an engine may read a heading last, or join a block across pages
def _above(blocks: list, start: int, at: int) -> set[int]:
    line = _top(blocks[at])
    return {i for i in range(start, at) if line is None or _top(blocks[i]) is None or _top(blocks[i]) < line}


def _span_of(blocks: list, page: int) -> tuple[int, int] | None:
    return next((s for s in _page_spans(blocks) if blocks[s[0]].book_page == page), None)


LABEL_WORDS = 5
LABEL_CHARS = 40
SENTENCE_END = tuple(".!?…。！？\"»”")


# a short line right over a title that ends no sentence is the title's label ("Chapter 7"), not the tail's last line
def _label(block) -> bool:
    text = " ".join(referee.block_text(block).split())
    return 0 < len(text.split()) <= LABEL_WORDS and len(text) <= LABEL_CHARS and not text.endswith(SENTENCE_END)


def _without_labels(blocks: list, above: set[int]) -> set[int]:
    kept = sorted(above)
    while kept and _label(blocks[kept[-1]]):
        kept.pop()
    return set(kept)


# both pieces cut the page alike from one reading: the tail is what is read before the title and set above it
def boundary_cut(blocks: list, boundary: Boundary) -> tuple[list, dict, float | None]:
    span = _span_of(blocks, boundary.page)
    if span is None:
        return blocks, {"page": boundary.page, "read": False}, None
    start, end = span
    at = titled(blocks, start + 1, end, boundary.title)
    over = _above(blocks, start + 1, at) if at is not None else set()
    above = _without_labels(blocks, over)
    # the cut runs over the title's labels too, so another engine's copy of a label stays with the title
    tops = [t for i in [*(over - above), *([at] if at is not None else [])] if (t := _top(blocks[i])) is not None]
    own = set(range(start + 1, end))
    drop = own - above if boundary.tail else above
    # a tail with nothing on the page leaves it whole, marker and all
    if boundary.tail and not above:
        drop.add(start)
    record = {"page": boundary.page, "read": True, "tail": boundary.tail, "title_found": at is not None,
              "title_top": min(tops) if tops else None,
              "tail_blocks": [referee.block_text(blocks[i])[:80] for i in sorted(above)], "dropped": len(drop),
              "tail_text": " ".join(referee.block_text(blocks[i]) for i in sorted(above)
                                    if not getattr(blocks[i], "slot", None))}
    return [b for i, b in enumerate(blocks) if i not in drop], record, record["title_top"]


# another engine's blocks on a boundary page on this piece's side of the title's top; a boxless one goes to neither
def _sided(blocks: list, boundary: Boundary, line: float | None) -> list:
    out, page = [], None
    for b in blocks:
        if isinstance(b, PageMarker):
            page = b.book_page
        elif page == boundary.page:
            top = _top(b)
            if top is None or (line is not None and top < line) != boundary.tail:
                continue
        out.append(b)
    return out


def cut_boundaries(blocks: list, others: dict[str, list],
                   boundaries: list[Boundary]) -> tuple[list, dict[str, list], list[dict]]:
    records = []
    for boundary in boundaries:
        blocks, record, line = boundary_cut(blocks, boundary)
        records.append(record)
        others = {e: _sided(b, boundary, line) for e, b in others.items()}
    return blocks, others, records


def shared_pages(blocks: list, title: str, shared_start: bool, next_title: str | None,
                 reread_page: int | None = None) -> tuple[list, dict]:
    counts = {"shared_cut_blocks": 0, "shared_title_missing": 0, "shared_cut_start": 0, "shared_cut_end": 0}
    spans = _page_spans(blocks)
    if not spans:
        return blocks, counts
    drop: set[int] = set()
    own = None
    # a piece that starts on its last page seeks its own title there too, so the next title is sought after it
    if shared_start or (next_title and len(spans) == 1):
        start, end = spans[0]
        own = titled(blocks, start + 1, end, title)
    if shared_start:
        if own is None:
            counts["shared_title_missing"] += 1
        else:
            drop.update(_above(blocks, spans[0][0] + 1, own))
            counts["shared_cut_start"] = 1
    # a re-read page the engine gave nothing for is not there to cut: the last page read is the piece's own
    tail = [s for s in spans if reread_page is None or blocks[s[0]].book_page == reread_page]
    if next_title and not tail:
        counts["shared_title_missing"] += 1
    elif next_title:
        start, end = tail[-1]
        after = start + 1 if own is None or own < start else own + 1
        nxt = titled(blocks, after, end, next_title)
        if nxt is None:
            counts["shared_title_missing"] += 1
            # a page read again only to cut the tail at: with no title on it, it is wholly the next piece's
            if reread_page is not None:
                drop.update(range(start + 1, end))
        else:
            drop.update(set(range(start + 1, end)) - _above(blocks, start + 1, nxt))
            counts["shared_cut_end"] = 1
    counts["shared_cut_blocks"] = len(drop)
    return [b for i, b in enumerate(blocks) if i not in drop], counts


def _book_pages(blocks: list) -> list[int | None]:
    out, page = [], None
    for b in blocks:
        page = b.book_page if isinstance(b, PageMarker) else page
        out.append(page)
    return out


def _plain(text: str) -> str:
    return " ".join(text.split()).lower()


# each sub-entry pinned to the heading closest to its title, one heading per entry, a contested one to the earlier
def pins(blocks: list, titles: list[str], counts: dict | None = None,
         pages: list[tuple[int, int]] | None = None) -> list[int | None]:
    taken: set[int] = set()
    fixed = _namesake_pins(blocks, titles, pages) if pages else {}
    taken.update(i for i in fixed.values() if i is not None)
    out = []
    for n, title in enumerate(titles):
        if n in fixed:
            out.append(fixed[n])
            continue
        fits = [(fuzz.ratio(_plain(b.text), _plain(title)), -i) for i, b in enumerate(blocks)
                if isinstance(b, Heading) and i not in taken and same_title(b.text, title)]
        best = -max(fits)[1] if fits else None
        if best is None and counts is not None and any(same_title(blocks[i].text, title) for i in taken):
            counts["pins_contested"] = counts.get("pins_contested", 0) + 1
        out.append(best)
        if best is not None:
            taken.add(best)
    return out


NAMESAKE_RATIO = 90


# nodes of one exact title ("Review questions") take its headings in page order, own pages first, never a namesake's
def _namesake_pins(blocks: list, titles: list[str], pages: list[tuple[int, int]]) -> dict[int, int | None]:
    page_at = _book_pages(blocks)
    groups: dict[str, list[int]] = {}
    for n, title in enumerate(titles):
        groups.setdefault(_plain(title), []).append(n)
    out: dict[int, int | None] = {}
    for title, nodes in groups.items():
        if len(nodes) < 2:
            continue
        # only a heading spelling the title itself: "SASL" is not one of the "SSL" nodes
        heads = [i for i, b in enumerate(blocks) if isinstance(b, Heading) and same_title(b.text, title)
                 and fuzz.ratio(_plain(b.text), title) >= NAMESAKE_RATIO]

        def score(n: int, i: int, nodes: list[int] = nodes) -> int:
            at = page_at[i]
            own = at is not None and pages[n][0] <= at <= pages[n][1]
            # a namesake spanning this node's pages is its parent, not another chapter's node
            other = any(at is not None and pages[m][0] <= at <= pages[m][1]
                        and not pages[m][0] <= pages[n][0] <= pages[n][1] <= pages[m][1] for m in nodes if m != n)
            return 2 if own else (0 if other else 1)

        # the best rising match of nodes to headings: most pins on own pages, then most pins
        best = [[(0, ())] * (len(heads) + 1) for _ in range(len(nodes) + 1)]
        for a in range(len(nodes) - 1, -1, -1):
            for b in range(len(heads) - 1, -1, -1):
                skip_node, skip_head = best[a + 1][b], best[a][b + 1]
                options = [skip_node, skip_head]
                if score(nodes[a], heads[b]):
                    got, pairs = best[a + 1][b + 1]
                    options.append((got + score(nodes[a], heads[b]), ((nodes[a], heads[b]), *pairs)))
                best[a][b] = max(options, key=lambda o: o[0])
        chosen = dict(best[0][0][1])
        out.update({n: chosen.get(n) for n in nodes})
    return out


# a pinned sub-entry gives its heading's level, the rest keep the engine's order from 1; past the ceiling demoted
def piece_levels(blocks: list, node_level: int, subs: list[tuple[str, int]],
                   pinned: list[int | None] | None = None) -> tuple[list, dict]:
    pinned = pins(blocks, [title for title, _ in subs]) if pinned is None else pinned
    level_at = {i: lvl for i, (_, lvl) in zip(pinned, subs, strict=True) if i is not None}
    ceiling = MAX_LEVEL - (node_level + 1)
    heads = [b for b in blocks if isinstance(b, Heading)]
    top = min((h.level for h in heads), default=1)
    counts = {"headings_from_structure": 0, "headings_demoted": 0, "headings_flattened": 0}
    out = []
    for i, b in enumerate(blocks):
        # a piece at the deepest level leaves no level for headings inside it: they stay as paragraphs
        if isinstance(b, Heading) and ceiling < 1:
            counts["headings_flattened"] += 1
            b = Paragraph(text=b.text, where=b.where)
        elif isinstance(b, Heading):
            sub = level_at.get(i)
            if sub is not None:
                level, source = max(1, sub - node_level), "structure"
                counts["headings_from_structure"] += 1
            else:
                level, source = b.level - top + 1, b.level_source
            if level > ceiling:
                counts["headings_demoted"] += 1
                level = ceiling
            b = b.model_copy(update={"level": min(level, 5), "level_source": source})
        out.append(b)
    return out, counts


# recognised pages have no layer to judge by: the text is one engine's, the two engines' word agreement is the measure
def recognised(reads: dict, prefer: str, steps: list | None = None, min_words: int = 0,
               boundaries: list[Boundary] = (), records: list | None = None) -> tuple[list, dict, dict[int, float]]:
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
    blocks, _, cut = cut_boundaries(reads[prefer].blocks, {}, list(boundaries))
    if records is not None:
        records += cut
    if steps is not None:
        steps.append(("recognised", blocks))
    return blocks, {"pages_recognised": len(agreement), "pages_picture": pictures}, agreement


# a chapter's section list: 3+ rows of its nodes' titles in order, two siblings, nothing longer than a title above
CONTENTS_MIN_ROWS = 3
CONTENTS_MAX_WORDS_ABOVE = 12
_ENTRY_NUMBER = re.compile(r"^\s*[\divxlcIVXLC]+([.\d]*)\s*[.:)]?\s+")
# a contents row ends in its page: Arabic after anything, Roman only after a leader, so "World War II" keeps its II
_ENTRY_TAIL = re.compile(rf"(?:[\s.·…_]*\d+|\s*[.·…_]{{2,}}\s*{numerals.ROMAN})\s*$")


def _entry(text: str) -> str:
    text = _ENTRY_TAIL.sub("", _ENTRY_NUMBER.sub("", text.strip()))
    return re.sub(r"[^\w]+", " ", text.lower()).strip()


# the rows of a page that make the run, as their indexes, for a node and the nodes under it (title, level) in order
def contents_rows(rows: list[str], under: list[tuple[str, int]]) -> list[int]:
    keys, titles = [_entry(r) for r in rows], [_entry(t) for t, _ in under]
    best: list[int] = []
    for start in range(len(keys)):
        j, k, taken, levels = start, 0, [], []
        while j < len(keys) and k < len(titles):
            two = (keys[j] + " " + keys[j + 1]).strip() if j + 1 < len(keys) else None
            hit = next((m for m in range(k, len(titles)) if titles[m] and titles[m] in (keys[j], two)), None)
            if hit is None:
                break
            width = 1 if keys[j] == titles[hit] else 2
            taken += range(j, j + width)
            levels.append(under[hit][1])
            j, k = j + width, hit + 1
        if len(levels) >= CONTENTS_MIN_ROWS and len(levels) > len(set(levels)) and len(taken) > len(best) \
                and all(len(r.split()) <= CONTENTS_MAX_WORDS_ABOVE for r in rows[:start]):
            best = taken
    return best


# the engine blocks on a node's first page standing wholly inside its contents run become one Contents block
def chapter_contents(blocks: list, nodes: list[dict], layer: dict[int, str]) -> tuple[list, int]:
    found = 0
    for n, node in enumerate(nodes):
        under = []
        for other in nodes[n + 1:]:
            if other["level"] <= node["level"]:
                break
            under.append((other["title"], other["level"]))
        page = node.get("first_page")
        if len(under) < CONTENTS_MIN_ROWS or page not in layer:
            continue
        rows = [r for r in layer[page].splitlines() if r.strip()]
        run = contents_rows(rows, under)
        if not run:
            continue
        keys = [_entry(rows[i]) for i in run]
        spans = [(a, b) for a, b in _page_spans(blocks) if blocks[a].book_page == page]
        if not spans:
            continue
        start, end = spans[0]
        inside = [i for i in range(start + 1, end) if isinstance(blocks[i], (Paragraph, Heading, ListBlock))
                  and _within_run(blocks[i], keys)]
        groups = _consecutive(inside)
        best = max(groups, key=lambda g: sum(len(referee.block_text(blocks[i]).splitlines()) for i in g), default=[])
        if not best:
            continue
        entries = [line for i in best for line in _lines(blocks[i])]
        if len(entries) < CONTENTS_MIN_ROWS:
            continue
        block = Contents(entries=entries, where=blocks[best[0]].where)
        blocks = blocks[:best[0]] + [block] + blocks[best[-1] + 1:]
        found += 1
    return blocks, found


# a list's lines with its nested lists', so none of them is lost when the list becomes a Contents block
def _lines(block) -> list[str]:
    if isinstance(block, ListBlock):
        return [line for i in block.items for line in [i.text, *(x for sub in i.children for x in _lines(sub))]]
    return [x for x in block.text.splitlines() if x.strip()]


def _within_run(block, keys: list[str]) -> bool:
    lines = [_entry(x) for x in _lines(block)]
    joined = " ".join(keys)
    return bool(lines) and all(x and (x in keys or x in joined) for x in lines)


def _consecutive(indexes: list[int]) -> list[list[int]]:
    groups: list[list[int]] = []
    for i in indexes:
        if groups and groups[-1][-1] == i - 1:
            groups[-1].append(i)
        else:
            groups.append([i])
    return groups


# a block opening with a caption of the book's own series is that caption, the paragraph's rest after it stays
def series_captions(blocks: list, captions: dict[int, list[str]]) -> tuple[list, int]:
    out, page, n = [], None, 0
    for k, b in enumerate(blocks):
        if isinstance(b, PageMarker):
            page = b.book_page
        wanted = captions.get(page, []) if page is not None else []
        if wanted and isinstance(b, (Paragraph, Heading)) and not (isinstance(b, Heading) and b.node is not None) \
                and _names_something(blocks, k):
            cut = next((c for w in wanted if (c := _caption_cut(b.text, w)) is not None), None)
            if cut is not None:
                head, rest = b.text[:cut].strip(), b.text[cut:].strip()
                out.append(Caption(text=head, where=b.where))
                if rest:
                    out.append(Paragraph(text=rest, where=b.where))
                n += 1
                continue
        out.append(b)
    return out, n


CAPTION_PREFIX = 0.9
# a caption stands by what it names: a picture, a table or a listing within this many blocks on its page
CAPTION_REACH = 2


def _names_something(blocks: list, k: int) -> bool:
    for step in (-1, 1):
        for j in range(k + step, k + step * (CAPTION_REACH + 1), step):
            if not 0 <= j < len(blocks) or isinstance(blocks[j], PageMarker):
                break
            if isinstance(blocks[j], (Figure, Table, Code)):
                return True
    return False


# where a caption's letters end inside a block that opens with them, or None when the block does not open with them
def _caption_cut(text: str, caption: str) -> int | None:
    at = [i for i, c in enumerate(text) if not c.isspace()]
    letters, want = "".join(text[i] for i in at), "".join(caption.split())
    pairs = zip(letters, want, strict=False)
    same = next((k for k, (a, b) in enumerate(pairs) if a != b), min(len(letters), len(want)))
    if not want or same < CAPTION_PREFIX * len(want) and same < len(letters):
        return None
    return at[same - 1] + 1 if same else None

