# a node's own outline printed on its opening page (an article of an edited volume) gives the node its children
import text_layer

from stages.structure.sources import Entry, conf
from stages.structure.sources import printed_contents as contents

OPENING_PAGES = 2


def _ends(entries: list[Entry], total: int) -> list[int]:
    out = []
    for i, e in enumerate(entries):
        nxt = next((x.page for x in entries[i + 1:] if x.page is not None and (x.level or 1) <= (e.level or 1)), None)
        out.append(total if nxt is None else max(e.page or 1, nxt - 1))
    return out


def _below(entries: list[Entry], i: int) -> int:
    level = entries[i].level or 1
    return next((j for j in range(i + 1, len(entries)) if (entries[j].level or 1) <= level), len(entries))


# the outline's rows inside the node by the book's offset, mostly rising, up to the first pointing out (a footnote's)
def _outline(node: Entry, last: int, lines: dict[int, list[text_layer.Line]], offset: int, total: int,
             contents_pages: frozenset[int]) -> list[Entry]:
    opening = [p for p in range(node.page, node.page + OPENING_PAGES) if p in lines and p <= last]
    if any(p in contents_pages for p in opening):
        return []
    parsed, _ = contents.parse(opening, lines, total)
    numbered = []
    for e, line, p in parsed:
        if e.printed is None or not str(e.printed).isdigit():
            continue
        if not node.page <= int(e.printed) + offset <= last:
            break
        numbered.append((e, line, p))
    pages = [int(e.printed) + offset for e, _, _ in numbered]
    if len(numbered) < conf()["contents"]["min_lines"]:
        return []
    rising = sum(b >= a for a, b in zip(pages, pages[1:], strict=False))
    if rising < contents.CONTENTS_RISING * (len(pages) - 1):
        return []
    return [Entry(e.title, (node.level or 1) + level, page, e.printed, evidence=f"outline on page {p}",
                  source="outline")
            for (e, _, p), level, page in zip(numbered, _levels(numbered), pages, strict=True)]


# an outline sets "II." and its "1." apart by indent alone, so its levels go by size, weight and indent
def _levels(rows: list) -> list[int]:
    steps = contents._indent_steps([max(line.x, 0) for _, line, _ in rows])
    keys = [(-line.size, not line.bold, steps[max(line.x, 0)]) for _, line, _ in rows]
    rank = {k: i + 1 for i, k in enumerate(sorted(set(keys)))}
    return [rank[k] for k in keys]


# the outline replaces what other sources found under a node only when it lists more; no outline on contents pages
def fold(entries: list[Entry], lines: dict[int, list[text_layer.Line]], offset: int | None, total: int,
         contents_pages: frozenset[int] = frozenset()) -> tuple[list[Entry], list[dict]]:
    if offset is None:
        return entries, []
    out, folded, i = [], [], 0
    ends = _ends(entries, total)
    while i < len(entries):
        node, below = entries[i], _below(entries, i)
        outline = _outline(node, ends[i], lines, offset, total, contents_pages) if node.page is not None else []
        if len(outline) > below - i - 1:
            out += [node, *outline]
            folded.append({"title": node.title, "page": node.page, "rows": len(outline), "replaced": below - i - 1})
            i = below
            continue
        out.append(node)
        i += 1
    return out, folded
