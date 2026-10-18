# which engine's reading to take for each page, judged only by the book's own text layer
import re
from collections import Counter

from document.model import Code, Contents, Formula, ListBlock, PageMarker, Table

# Chinese, Japanese and Korean write no spaces between words, so each of their characters counts as a word
CJK = "\u3040-\u30ff\u3130-\u318f\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\uf900-\ufaff"
WORD = re.compile(rf"[{CJK}]|(?:(?![{CJK}])\w)+")


def block_text(block) -> str:
    match block:
        case Code():
            return block.text
        case Formula():
            return block.latex
        case Table():
            return " ".join(c.text for row in block.rows for c in row)
        case ListBlock():
            return " ".join(i.text + " " + " ".join(block_text(c) for c in i.children) for i in block.items)
        case Contents():
            return " ".join(block.entries)
    return getattr(block, "text", "")


def f1(a: Counter, b: Counter) -> float:
    common = sum((a & b).values())
    if not common:
        return 0.0
    precision, recall = common / sum(b.values()), common / sum(a.values())
    return 2 * precision * recall / (precision + recall)


def by_page(blocks: list) -> dict[int, list]:
    out: dict[int, list] = {}
    page = None
    for b in blocks:
        if isinstance(b, PageMarker):
            page = b.file_page
            out.setdefault(page, [])
        elif page is not None:
            out[page].append(b)
    return out


# a page goes to the engine whose words agree best with the layer; a page without a layer keeps the first engine
def per_page(readings: dict[str, list], layer: dict[int, str], order: tuple[str, ...]) -> tuple[list, dict[int, dict]]:
    pages = {engine: by_page(blocks) for engine, blocks in readings.items()}
    markers = {b.file_page: b for blocks in readings.values() for b in blocks if isinstance(b, PageMarker)}
    out, picks = [], {}
    for page in sorted(markers):
        words = Counter(WORD.findall(layer.get(page, "").lower()))
        scores = {e: f1(words, Counter(WORD.findall(" ".join(block_text(b) for b in pages[e].get(page, [])).lower())))
                  for e in order if e in pages}
        best = max(order, key=lambda e: (scores.get(e, -1), -order.index(e))) if words else order[0]
        picks[page] = {"picked": best, "scores": {e: round(s, 3) for e, s in scores.items()}}
        out.append(markers[page])
        out += pages[best].get(page, [])
    return out, picks
