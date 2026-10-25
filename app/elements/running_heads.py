# the running head element: lines repeated at a page's edge and bare folios, the blocks read of them, their measure
import re
from collections import Counter

from assembly.referee import WORD
from document.model import Caption, Heading, ListBlock, PageMarker, Paragraph, Piece

from elements import folding

RUNNING_PAGES = 3


def norm(text: str) -> str:
    return re.sub(r"[\W_]+", "", text.lower())


# a page number at either end differs from page to page; numbers inside ("Chapter 2") tell lines apart
def edge_key(text: str) -> str:
    return norm(re.sub(r"^\s*\d+\s+|\s+\d+\s*$", "", text))


# the running heads on each page, by line index; a piece's opening top line is its title, not a head
def per_page(lines: dict[int, list]) -> dict[int, list[int]]:
    edges, first = Counter(), {}
    for page in sorted(lines):
        page_lines = lines[page]
        for key in {edge_key(x.text) for x in (page_lines[:1] + page_lines[-1:])}:
            edges[key] += 1
        if page_lines:
            first.setdefault(edge_key(page_lines[0].text), page)
    running = {k for k, n in edges.items() if n >= RUNNING_PAGES and k}
    out = {}
    for page, page_lines in lines.items():
        out[page] = [i for i, x in enumerate(page_lines)
                     if (i == 0 or i == len(page_lines) - 1) and edge_key(x.text) in running
                     and not (i == 0 and first.get(edge_key(x.text)) == page)]
    return out


# a page number alone on the page's top or bottom line, bare or in dashes ("— 17 —")
FOLIO = re.compile(r"[\W_]*(\d{1,4})[\W_]*")


# the book's own furniture: running heads and bare page numbers that rise with the pages ("5" under a query is text)
def layer_heads(lines: dict[int, list]) -> dict[int, list[str]]:
    bare = {(page, i): page - int(m[1]) for page, page_lines in lines.items() for i in {0, len(page_lines) - 1}
            if page_lines and (m := FOLIO.fullmatch(page_lines[i].text))}
    shifts = Counter(bare.values())
    heads = {}
    for page, found in per_page(lines).items():
        texts = [x.text for i, x in enumerate(lines[page])
                 if i in found or shifts[bare.get((page, i))] >= RUNNING_PAGES]
        if texts:
            heads[page] = texts
    return heads


# a block whose whole text is a slot line its page layout claims, or its page's claimed lines run together, is marked
def mark_slots(blocks: list, slots: dict[int, list[tuple[str, str, float]]],
               parts: bool = False) -> tuple[list, int]:
    out, n, here = [], 0, {}
    for b in blocks:
        if isinstance(b, PageMarker):
            lines = slots.get(b.file_page, [])
            here = {folding.fold(t): r for t, r, *_ in lines}
            if len(lines) > 1:
                here.setdefault(folding.fold(" ".join(t for t, *_ in lines)), lines[0][1])
        elif here and isinstance(b, (Heading, Paragraph, Caption)) and folding.fold(b.text) in here:
            b = b.model_copy(update={"slot": here[folding.fold(b.text)]})
            n += 1
        elif here and isinstance(b, ListBlock) and any(folding.fold(i.text) in here for i in b.items):
            items = [i.model_copy(update={"slot": here[folding.fold(i.text)]}) if folding.fold(i.text) in here else i
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
            words = folding.fold(text).split()
            near = [k for k in ks if not out[k].slot and abs(out[k].where.box[1] - top) <= SLOT_BAND]
            spans = [(k, folding.span(words, folding.fold(out[k].text).split())) for k in near]
            spans = [(k, s) for k, s in spans if s is not None and s[1] - s[0] < len(words)]
            covered = sorted(s for _, s in spans)
            if len(covered) < 2 or covered[0][0] != 0 or covered[-1][1] != len(words) or \
                    any(a[1] != b[0] for a, b in zip(covered, covered[1:], strict=False)):
                continue
            for k, _ in spans:
                out[k] = out[k].model_copy(update={"slot": reason})
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


# running heads and folios left as a paragraph or an unpinned heading (a node's title is often its head), or glued
def in_text(piece: Piece, furniture: dict[str, list[str]]) -> dict:
    lines = furniture.get("layer", [])
    heads = {key for h in lines if (key := edge_key(h))}
    folios = {m[1] for h in lines if (m := FOLIO.fullmatch(h))}
    def left(text: str) -> bool:
        folio = FOLIO.fullmatch(text)
        return edge_key(text) in heads or bool(folio and folio[1] in folios)

    phrases = {p for h in lines if len(p := tuple(_head_words(h))) >= GLUED_WORDS}
    def glued(text: str) -> bool:
        got = tuple(WORD.findall(text.lower()))
        return any(len(got) > len(p) and (got[:len(p)] == p or got[-len(p):] == p) for p in phrases)

    alone = sum((isinstance(b, Paragraph) or isinstance(b, Heading) and b.node is None) and left(b.text)
                for b in piece.blocks)
    return {"running_heads_in_text": alone,
            "running_heads_glued": sum(isinstance(b, Paragraph) and glued(b.text) for b in piece.blocks)}


GLUED_WORDS = 2


# a running head's words without the folio at either end
def _head_words(line: str) -> list[str]:
    words = WORD.findall(line.lower())
    while words and words[0].isdigit():
        words = words[1:]
    while words and words[-1].isdigit():
        words = words[:-1]
    return words
