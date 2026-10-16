# a section's Markdown scored per element against its gold: code, table cells, headings, text, running heads
import re
import unicodedata
from collections import Counter

from assembly import referee
from assembly.passes import same_title
from document.model import Figure, Formula, PageMarker, Paragraph
from rapidfuzz import fuzz

FENCE = re.compile(r"^(`{3,}|~{3,})[^\n]*\n(.*?)^\1[ \t]*$", re.M | re.S)
HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$", re.M)
CELL_TAG = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S | re.I)
# a tag has a name and ends on its own line, so `<-` or `a < b ... >` in code is not one
TAG = re.compile(r"</?[A-Za-z][^<>\n]*>")
RULE_CELL = re.compile(r"^:?-{3,}:?$")
IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
MARKS = re.compile(r"[#>*|`_\\]|^\s*[-+]\s", re.M)
TYPOGRAPHY = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "«": '"',
                            "»": '"', "–": "-", "—": "-", "−": "-", " ": " "})


def squash(text: str) -> str:
    return " ".join(text.split())


# pandoc sets code from LaTeX and Sphinx sources as blocks indented by four spaces after a blank line
INDENTED = re.compile(r"(?:(?<=\n\n)|\A)((?:(?: {4}|\t).*\n|[ \t]*\n)*(?: {4}|\t).*(?:\n|\Z))")
LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s")


def _indented(markdown: str) -> list[re.Match]:
    text = FENCE.sub(lambda m: "\n" * m.group(0).count("\n"), markdown)
    out = []
    for m in INDENTED.finditer(text):
        before = text[:m.start()].rstrip("\n").rsplit("\n", 1)[-1]
        # a list item's own continuation is indented the same way, so a block right after a list item is not code
        if not LIST_ITEM.match(before):
            out.append(m)
    return out


def code_blocks(markdown: str) -> list[str]:
    fenced = [m.group(2) for m in FENCE.finditer(markdown)]
    indented = ["\n".join(line[4:] if line.startswith("    ") else line.lstrip("\t")
                          for line in m.group(1).rstrip("\n").splitlines()) + "\n" for m in _indented(markdown)]
    return fenced + indented


def _outside_code(markdown: str) -> str:
    text = FENCE.sub("", markdown)
    for m in reversed(_indented(text)):
        text = text[:m.start()] + text[m.end():]
    return text


def headings(markdown: str) -> list[str]:
    return [squash(m.group(2)) for m in HEADING.finditer(_outside_code(markdown))]


# a cell is compared by its words: code and emphasis marks inside it are the gold's markup, not its text
def _cell(text: str) -> str:
    return squash(re.sub(r"[`*_]", "", TAG.sub(" ", text))).lower()


def cells(markdown: str) -> Counter:
    # pandoc from Sphinx sets some tables inside a quote; the quote marks are not part of the cells
    text = re.sub(r"^>\s?", "", _outside_code(markdown), flags=re.M)
    found = [_cell(c) for c in CELL_TAG.findall(text)]
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("|") and line.endswith("|"):
            found += [_cell(c) for c in re.split(r"(?<!\\)\|", line[1:-1])]
    return Counter(c for c in found if c and not RULE_CELL.match(c))


TR = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
CELL_SPAN = re.compile(r"<t[dh]([^>]*)>(.*?)</t[dh]>", re.S | re.I)
COLSPAN = re.compile(r"colspan=\"?(\d+)")


# a row compares cells without their spaces, and a cell of a mark alone as empty: the gold drops check marks
def _row_cell(text: str) -> str:
    bare = re.sub(r"[\s\u200b-\u200d\u2060\ufeff]", "", text)
    return "" if bare and not re.search(r"\w", bare) else bare


# table rows as tuples of cells, a spanned cell repeated over its columns, so a shifted column is a different row
def table_rows(markdown: str) -> list[tuple]:
    text = re.sub(r"^>\s?", "", _outside_code(markdown), flags=re.M)
    rows = []
    for tr in TR.findall(text):
        row = []
        for attrs, cell in CELL_SPAN.findall(tr):
            span = int(m.group(1)) if (m := COLSPAN.search(attrs)) else 1
            row += [_row_cell(_cell(cell))] * span
        rows.append(tuple(row))
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("|") and line.endswith("|"):
            row = tuple(_row_cell(_cell(c)) for c in re.split(r"(?<!\\)\|", line[1:-1]))
            if not all(RULE_CELL.match(c) for c in row if c):
                rows.append(row)
    return [r for r in rows if any(r)]


def table_rows_raw(markdown: str) -> list[list[str]]:
    text = re.sub(r"^>\s?", "", _outside_code(markdown), flags=re.M)
    rows = [[_cell(c) for _, c in CELL_SPAN.findall(tr)] for tr in TR.findall(text)]
    rows += [[_cell(c) for c in re.split(r"(?<!\\)\|", line.strip()[1:-1])] for line in text.splitlines()
             if line.strip().startswith("|") and line.strip().endswith("|")]
    return rows


def _tags_outside_code(text: str) -> str:
    out, at = [], 0
    for m in FENCE.finditer(text):
        out += [TAG.sub(" ", text[at:m.start()]), m.group(0)]
        at = m.end()
    return "".join(out + [TAG.sub(" ", text[at:])])


def plain(markdown: str) -> str:
    # the writer's comments (node marks, figures not kept) are not the book's text
    text = re.sub(r"<!--.*?-->", " ", markdown, flags=re.S)
    text = _tags_outside_code(unicodedata.normalize("NFKC", text).translate(TYPOGRAPHY))
    # cross-references and anchors pandoc left unresolved are the gold's own artefacts
    text = re.sub(r"\[\?\?\?\]\([^)]*\)|\{#[^}]*\}", "", text)
    text = re.sub(r"^(`{3,}|~{3,}).*$", "", text, flags=re.M)
    text = LINK.sub(r"\1", IMAGE.sub("", text))
    return squash(MARKS.sub(" ", text))


# words, not whitespace runs: a comma set apart by spaces is spacing, not a word the gold lacks
def _f1(gold: str, got: str) -> float:
    return referee.f1(Counter(re.findall(r"\w+", gold.lower())), Counter(re.findall(r"\w+", got.lower())))


SLACK = 0.01


def _inside(where, clips: list[tuple[int, tuple]]) -> bool:
    x, y = (where.box[0] + where.box[2]) / 2, (where.box[1] + where.box[3]) / 2
    return any(where.page == page and box[0] - SLACK <= x <= box[2] + SLACK and box[1] - SLACK <= y <= box[3] + SLACK
               for page, box in clips)


# the section is the blocks whose centre lies inside the gold's own boxes, whatever the engine called its headings
def section(blocks: list, clips: list[tuple[int, tuple]]) -> tuple[list, int]:
    pages = {page for page, _ in clips}
    out, page, unplaced = [], None, 0
    for b in blocks:
        if isinstance(b, PageMarker):
            page = b.file_page
            if page in pages:
                out.append(b)
        elif b.where is not None:
            if _inside(b.where, clips):
                out.append(b)
        elif page in pages:
            unplaced += 1
            out.append(b)
    return out, unplaced


def _norm_line(text: str) -> str:
    return squash(re.sub(r"\d+", "", text)).lower()


# lines first or last on two or more pages of the cut's text layer are its running heads
def running_lines(lines: dict) -> set[str]:
    edges = Counter()
    for page_lines in lines.values():
        texts = {_norm_line(x.text) for x in (page_lines[:1] + page_lines[-1:])}
        edges.update(t for t in texts if len(t) > 3)
    return {t for t, n in edges.items() if n >= 2}


def score(gold_md: str, got_md: str, blocks: list, running: set[str]) -> dict:
    gold_code, got_code = code_blocks(gold_md), code_blocks(got_md)
    got_joined = "\n".join(squash(c) for c in got_code)
    gold_joined = "\n".join(squash(c) for c in gold_code)
    gold_cells, got_cells = cells(gold_md), cells(got_md)
    gold_heads, got_heads = headings(gold_md), headings(got_md)
    free, found_heads = list(got_heads), 0
    for g in gold_heads:
        hit = next((h for h in free if same_title(g, h)), None)
        if hit is not None:
            free.remove(hit)
            found_heads += 1
    gold_plain, got_plain = plain(gold_md), plain(got_md)
    leaked = [b.text for b in blocks if isinstance(b, Paragraph) and _norm_line(b.text) in running]
    return {
        "code": len(gold_code),
        "code_exact": sum(any(c.rstrip() == o.rstrip() for o in got_code) for c in gold_code),
        "code_contained": sum(squash(c) in got_joined for c in gold_code),
        "code_out": len(got_code),
        "code_out_foreign": sum(squash(o) not in gold_joined and not any(squash(c) in squash(o) for c in gold_code)
                                for o in got_code if squash(o)),
        "code_out_merged": sum(squash(o) not in gold_joined and any(squash(c) in squash(o) for c in gold_code)
                               for o in got_code if squash(o)),
        "cells": sum(gold_cells.values()),
        "cells_found": sum((gold_cells & got_cells).values()),
        "cells_out": sum(got_cells.values()),
        "table_rows": len(gold_rows := table_rows(gold_md)),
        "table_rows_exact": sum((Counter(gold_rows) & Counter(table_rows(got_md))).values()),
        # a word broken by a line end inside a cell ("write- ahead") is a defect the row compare does not see
        "cells_broken_hyphen": len(re.findall(r"\w- \w", " ".join(" ".join(r) for r in table_rows_raw(got_md)))),
        "headings": len(gold_heads),
        "headings_found": found_heads,
        "headings_phantom": len(free),
        "similarity": round(fuzz.ratio(gold_plain, got_plain), 1),
        "body_f1": round(_f1(gold_plain, got_plain), 3),
        "running_leaked": len(leaked),
        "figures_gold": len(IMAGE.findall(gold_md)),
        "figures_out": sum(isinstance(b, Figure) for b in blocks),
        "formulas_gold": gold_md.count("$$") // 2,
        "formulas_out": sum(isinstance(b, Formula) for b in blocks),
        "pages": sum(isinstance(b, PageMarker) for b in blocks),
    }


# the gold against the layer lines inside its own boxes: a short cousin of a long section fails here, not on the cut
def gold_in_clips(gold_md: str, lines: dict, clips: list[tuple[int, tuple]], sizes: list[tuple]) -> dict:
    inside = []
    for page, box in clips:
        height = sizes[page - 1][1]
        inside += [x.text for x in lines.get(page - 1, []) if box[1] - 0.01 <= x.top / height <= box[3] + 0.01]
    gold = Counter(re.findall(r"\w+", plain(gold_md).lower()))
    clip = Counter(re.findall(r"\w+", " ".join(inside).lower()))
    return {"gold_clip_f1": round(_f1(" ".join(gold.elements()), " ".join(clip.elements())), 2),
            "gold_words": sum(gold.values()), "clip_words": sum(clip.values())}
