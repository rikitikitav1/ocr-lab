# repeated top and bottom lines of a book's pages are its running heads; read from the text layer alone
import re
from collections import Counter

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
