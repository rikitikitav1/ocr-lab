# the assembler's passes over a piece's blocks; each reads only the book, never a gold
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from functools import cache

import settings
import yaml
from document.model import Caption, Heading, PageMarker, Paragraph
from elements import captions as book_captions
from elements import code, footnotes, geometry, running_heads, tables
from rapidfuzz import fuzz

from assembly import referee
from assembly.titles import same_title


def conf_text() -> str:
    return (settings.CONFIG_DIR / "assembly.yaml").read_text()


@cache
def conf() -> dict:
    return yaml.safe_load((settings.CONFIG_DIR / "assembly.yaml").read_text())["passes"]


# a page two pieces meet on: the next piece's title, and which side this piece takes of it
@dataclass(frozen=True)
class Boundary:
    page: int
    title: str
    tail: bool


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
        blocks, counts["notes_from_furniture"] = footnotes.notes_from_furniture(blocks, reads, picked, notes)
        steps.append(("notes_from_furniture", blocks))
    if captions and on.get("caption_series"):
        blocks, counts["captions_from_furniture"] = book_captions.captions_from_furniture(blocks, reads, picked,
                                                                                          captions)
        steps.append(("captions_from_furniture", blocks))
    # an engine's spaced row is joined before the slots are matched, since the layout reads its lines joined
    if joined_rows:
        blocks, counts["rows_respaced"] = respaced(blocks, joined_rows)
        steps.append(("respaced", blocks))
    # slots are marked first, so a boundary's tail, the earlier piece's own text, leaves its running head out
    if slots:
        blocks, counts["slot_marked"] = running_heads.mark_slots(blocks, slots, bool(on.get("slot_parts")))
    # the boundary pages are cut before any pass, so no pass works on the neighbour's half
    blocks, others, cut = cut_boundaries(blocks, {e: r.blocks for e, r in reads.items()}, list(boundaries))
    if records is not None:
        records += cut
    for page in picked.values():
        counts[f"pages_{page['picked']}"] = counts.get(f"pages_{page['picked']}", 0) + 1
    if preferred := on.get("tables_from"):
        if on.get("tables_by") == "layer":
            blocks, counts["tables_swapped"] = tables.tables_by_layer(blocks, others[preferred], glyphs)
        else:
            blocks, counts["tables_swapped"] = tables.tables_from(blocks, others[preferred])
        steps.append(("tables", blocks))
    if on.get("table_union") and preferred:
        blocks, counts["tables_added"] = tables.table_union(blocks, others[preferred], glyphs)
        steps.append(("table_union", blocks))
    if on.get("code_union"):
        blocks, counts["code_added"] = code.code_union(blocks, list(others.values()), glyphs)
        steps.append(("code_union", blocks))
    if on.get("mono_paragraphs"):
        blocks, counts["paragraphs_to_code"] = code.mono_paragraphs(blocks, glyphs)
        steps.append(("mono_paragraphs", blocks))
    if on.get("code_from_layer"):
        blocks, counts["code_rebuilt"] = code.code_from_layer(blocks, glyphs)
        blocks, counts["code_fragments"] = code.drop_code_fragments(blocks)
        steps.append(("code_from_layer", blocks))
    if on.get("join_code_across_pages"):
        blocks, counts["code_joined"] = code.join_code_across_pages(blocks)
        steps.append(("join_code_across_pages", blocks))
    return blocks, counts


MAX_LEVEL = 6


# the piece's own title set again on its first page is the writer's heading already, so it goes
def without_title(blocks: list, title: str) -> tuple[list, int]:
    # the title's label set over it ("Chapter 1") stays as the book's text, the title the writer sets goes
    first = next((i for i, b in enumerate(blocks) if not isinstance(b, PageMarker)
                  and not (_label(b) and not same_title(referee.block_text(b), title))), None)
    if first is not None and isinstance(blocks[first], Heading) and same_title(blocks[first].text, title):
        return blocks[:first] + blocks[first + 1:], 1
    return blocks, 0


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
    spans = geometry.page_spans(blocks)
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
    return next((s for s in geometry.page_spans(blocks) if blocks[s[0]].book_page == page), None)


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
    spans = geometry.page_spans(blocks)
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
    # a page one engine read nothing on is its failure there, not a disagreement, and is counted apart
    empty = {f"pages_empty_{e}": 0 for e in (prefer, other)}
    for page in pages[prefer]:
        words = {e: Counter(referee.WORD.findall(" ".join(referee.block_text(b) for b in pages[e].get(page, []))
                                                 .lower())) for e in (prefer, other)}
        # a plate's caption against nothing is no measure of recognition; one engine failing alone is not a plate
        if max(sum(w.values()) for w in words.values()) < min_words:
            pictures += 1
            continue
        for e, w in words.items():
            empty[f"pages_empty_{e}"] += not w
        agreement[page] = round(referee.f1(words[prefer], words[other]), 3)
    blocks, _, cut = cut_boundaries(reads[prefer].blocks, {}, list(boundaries))
    if records is not None:
        records += cut
    if steps is not None:
        steps.append(("recognised", blocks))
    return blocks, {"pages_recognised": len(agreement), "pages_picture": pictures, **empty}, agreement
