# a chapter's own list of its sections on its opening page, set apart as one Contents block a reader can leave out
import re

import numerals
from assembly import referee
from document.model import Contents, Heading, ListBlock, Paragraph

from elements import geometry

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
        spans = [(a, b) for a, b in geometry.page_spans(blocks) if blocks[a].book_page == page]
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
