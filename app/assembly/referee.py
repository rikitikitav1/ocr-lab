# which engine's reading to take for each page, judged only by the book's own text layer
from collections import Counter

from document.model import PageMarker
from document.text import CJK, WORD, block_text, f1  # noqa: F401


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
