# the contents pages printed in the book: lines ending in a page number, levels from their style and indent
import re
from collections import Counter

import numerals
import pdf
from orm.catalogue import BookFile

from stages import running_heads
from stages.toc.sources import PRINTED_AHEAD, Entry, SourceToc, book_lines, conf, pages_of, windows
from stages.toc.sources.numbering import title_depth

LEADER = r"(?:\s*(?:\.\s?|·\s?|…|_){2,}\s*|\s{2,}|\s)"
ENTRY = re.compile(rf"^(?P<title>.*?\S){LEADER}(?P<page>{numerals.PAGE})$", re.I)
DOTTED = re.compile(rf"(?:\.\s?|·\s?|…){{3,}}\s*{numerals.PAGE}$", re.I)
TRAILING_LEADER = re.compile(r"[\s.·…_]+$")
INDENT_GAP = 5
NUMBERED_SHARE = 0.5
READ_AHEAD = 20
WATERMARK_SAMPLE = 40
WATERMARK_SHARE = 0.6
FOLIO = re.compile(rf"^\s*{numerals.PAGE}\s*$", re.I)
JOIN_SLACK = 3


def _heading_words() -> set[str]:
    return {running_heads.norm(w) for w in conf()["contents"]["headings"]}


# compared without spaces, since a text layer may set a heading letter by letter ("СОДЕРЖАНИ Е")
def _is_heading(text: str) -> bool:
    return bool(running_heads.norm(text)) and running_heads.norm(text) in _heading_words()


def _numbered(lines: list[pdf.Line]) -> int:
    return sum(bool(ENTRY.match(line.text)) for line in lines)


def _is_contents(lines: list[pdf.Line]) -> bool:
    need = conf()["contents"]["min_lines"]
    if sum(bool(DOTTED.search(line.text)) for line in lines) >= need:
        return True
    return any(_is_heading(line.text) for line in lines[:3]) and _numbered(lines) >= need


# a contents run goes on while the next page still lists entries, past the window if it must
def _contents_pages(files: list[BookFile], lines: dict[int, list[pdf.Line]]) -> list[int]:
    total = sum(f.pages for f in files)
    found = [p for p in sorted(lines) if _is_contents(lines[p])]
    for p in list(found):
        nxt = p + 1
        while nxt <= total and nxt not in found:
            if nxt not in lines:
                lines.update(book_lines(files, set(range(nxt, min(nxt + READ_AHEAD, total + 1)))))
            if _numbered(lines.get(nxt, [])) < conf()["contents"]["min_lines"]:
                break
            found.append(nxt)
            nxt += 1
    return sorted(set(found))


# the end of the book is searched only when its start has no contents, since an index looks like one
def find_pages(files: list[BookFile], given: list[list[int]] | None) -> tuple[list[int], dict[int, list[pdf.Line]]]:
    if given:
        pages = pages_of(given)
        return pages, book_lines(files, set(pages))
    head, tail = windows(sum(f.pages for f in files))
    lines = book_lines(files, set(head))
    found = _contents_pages(files, lines)
    if not found:
        lines = book_lines(files, set(tail))
        found = _contents_pages(files, lines)
    return found, lines


# the folio of a contents page is Arabic or Roman and may sit apart by a dash: "xiv Contents", "8 - Contents"
FOLIO_EDGE = re.compile(rf"^{numerals.PAGE}\s*[-–—|]?\s+|\s+[-–—|]?\s*{numerals.PAGE}$", re.I)


def _without_page_number(text: str) -> str:
    return FOLIO_EDGE.sub("", text.strip()).strip().lower()


# a contents heading topping several pages in the entries' size is a running head, a larger one a title
def _running_heads(pages: list[int], lines: dict[int, list[pdf.Line]]) -> tuple[set[str], float]:
    body = Counter(x.size for p in pages for x in lines.get(p, [])).most_common(1)
    body_size = body[0][0] if body else 0
    tops = Counter(_without_page_number(lines[p][0].text) for p in pages
                   if lines.get(p) and lines[p][0].size <= body_size)
    return {text for text, n in tops.items() if n >= 2 and _is_heading(text)}, body_size


# a line printed on most pages of the book (a download stamp, a licence line) is never an entry
def _without_watermarks(files: list[BookFile], pages: list[int], lines: dict[int, list[pdf.Line]]) -> dict:
    total = sum(f.pages for f in files)
    sample = book_lines(files, set(range(1, total + 1, max(1, total // WATERMARK_SAMPLE))))
    seen = Counter(text for page_lines in sample.values() for text in {x.text.strip() for x in page_lines})
    marks = {text for text, n in seen.items() if n >= WATERMARK_SHARE * len(sample) and len(sample) >= 5}
    return {p: [x for x in lines.get(p, []) if x.text.strip() not in marks] for p in pages}


def _running_head(line: pdf.Line, page_lines: list[pdf.Line], running: tuple[set[str], float]) -> bool:
    words, (repeated, body_size) = _without_page_number(line.text), running
    if line is not page_lines[0]:
        return False
    if words != line.text.strip().lower() and _is_heading(words):
        return True
    return line.size <= body_size and words in repeated


# centred lines without page numbers (a part title over two lines) join whatever their indent
def _continues(pending: pdf.Line, line: pdf.Line, numbered: bool) -> bool:
    return (pending.size, pending.bold) == (line.size, line.bold) and (not numbered or line.x >= pending.x - JOIN_SLACK)


# a wrapped title keeps its style and indent; a line breaking that ends the title above it
def _entries(page: int, lines: list[pdf.Line]) -> list[tuple[Entry, pdf.Line]]:
    out, pending = [], []
    for line in lines:
        m = ENTRY.match(line.text)
        # a Roman page number is lower case or follows a leader, or "Part I" reads as an entry on page I
        if m is not None and not m.group("page").isdigit() and not m.group("page").islower() \
                and not DOTTED.search(line.text):
            m = None
        if pending and not _continues(pending[-1], line, m is not None):
            out.append((Entry(" ".join(x.text for x in pending), None, evidence=f"contents page {page}"), pending[0]))
            pending = []
        if m is None:
            pending.append(line)
            continue
        title = TRAILING_LEADER.sub("", " ".join([*(x.text for x in pending), m.group("title")])).strip()
        first, pending = (pending[0] if pending else line), []
        if title:
            out.append((Entry(title, None, printed=m.group("page"), evidence=f"contents page {page}"), first))
    if pending:
        out.append((Entry(" ".join(x.text for x in pending), None, evidence=f"contents page {page}"), pending[0]))
    return out


# indents from the page's own left edge, or from pages of the same parity when only sections are there
def _indented(entries: list[tuple[Entry, pdf.Line, int]]) -> list[tuple[Entry, pdf.Line, int]]:
    numbered = [(e, line, page) for e, line, page in entries if e.printed is not None]
    top = min((title_depth(e.title) or 0 for e, _, _ in numbered), default=0)
    own, parity = {}, {}
    for e, line, page in numbered:
        own[page] = min(own.get(page, line.x), line.x)
        if (title_depth(e.title) or 0) == top:
            parity[page % 2] = min(parity.get(page % 2, line.x), line.x)
    tops = {page for e, _, page in numbered if (title_depth(e.title) or 0) == top}
    edge = {page: own[page] if page in tops else parity.get(page % 2, own[page]) for page in own}
    return [(e, pdf.Line(line.text, line.x - edge.get(page, line.x), line.top, line.size, line.bold), page)
            for e, line, page in entries]


# indents a few points apart are one indent: scanned layers drift, and a fixed grid splits them
def _indent_steps(xs: list[float]) -> dict[float, int]:
    steps, step, last = {}, 0, None
    for x in sorted(set(xs)):
        if last is not None and x - last > INDENT_GAP:
            step += 1
        steps[x], last = step, x
    return steps


# a book may print a brief contents and then a full one: each starts at a contents heading, the fullest wins


# the book's own contents covers the book; a chapter's contents beside it covers that chapter, however many lines
def _reach(block: list, total: int) -> tuple[int, int]:
    numbers = _pages_of(block, total)
    return (max(numbers) - min(numbers) if numbers else 0, sum(e.printed is not None for e, _, _ in block))


# a year in a footnote is not a page: printed numbers run past the PDF's pages by the front matter at most
def _pages_of(block: list, total: int) -> list[int]:
    numbers = [int(e.printed) for e, _, _ in block if e.printed is not None and str(e.printed).isdigit()]
    return [n for n in numbers if n <= total + PRINTED_AHEAD]


# a block whose numbers go on from the last one's is the same contents; one starting again is a chapter's own
def _continued(blocks: list[list], total: int) -> list[list]:
    out: list[list] = []
    for block in blocks:
        before, now = (_pages_of(out[-1], total) if out else []), _pages_of(block, total)
        if before and now and now[0] >= before[-1]:
            out[-1] = out[-1] + block
        else:
            out.append(block)
    return out


def parse(pages: list[int], lines: dict[int, list[pdf.Line]],
          total: int) -> tuple[list[tuple[Entry, pdf.Line, int]], list[int]]:
    blocks: list[list] = [[]]
    running = _running_heads(pages, lines)
    for p in pages:
        page_lines = [x for x in lines.get(p, [])
                      if not _running_head(x, lines[p], running) and not FOLIO.match(x.text)]
        start = 0
        for i, line in enumerate(page_lines):
            if _is_heading(line.text):
                blocks[-1] += [(e, line, p) for e, line in _entries(p, page_lines[start:i])]
                if blocks[-1]:
                    blocks.append([])
                start = i + 1
        blocks[-1] += [(e, line, p) for e, line in _entries(p, page_lines[start:])]
    blocks = [_indented(b) for b in _continued([b for b in blocks if b], total)]
    if not blocks:
        return [], []
    fullest = max(blocks, key=lambda b: _reach(b, total))
    return _headings_only(fullest), [len(b) for b in blocks if b is not fullest]


# a line without a page number is a title only when set larger than the entries, so the imprint drops
def _headings_only(block: list[tuple[Entry, pdf.Line, int]]) -> list[tuple[Entry, pdf.Line, int]]:
    sizes = Counter(line.size for e, line, _ in block if e.printed is not None)
    if not sizes:
        return block
    body = sizes.most_common(1)[0][0]
    return [(e, line, p) for e, line, p in block if e.printed is not None or line.size > body]


# a style seen once (a stray bold line) merges into the closest common one by size
def _styles(parsed: list[tuple[Entry, pdf.Line]]) -> dict[tuple, tuple]:
    seen = Counter((line.size, line.bold) for _, line in parsed)
    common = [s for s, n in seen.items() if n >= 2] or list(seen)
    return {s: s if s in common else min(common, key=lambda c: (abs(c[0] - s[0]), c[1] != s[1])) for s in seen}


def _depth(entry: Entry) -> int | None:
    return title_depth(entry.title, bare=True)


# an unnumbered entry is as deep as the nearest numbered one on its page, deeper if clearly indented
def _depths(parsed: list[tuple[Entry, pdf.Line, int]]) -> list[int]:
    out = []
    for entry, line, page in parsed:
        depth = _depth(entry)
        if depth is None:
            peers = [(abs(x.x - line.x), x.x, _depth(e)) for e, x, p in parsed if p == page and _depth(e) is not None]
            if peers:
                _, x, depth = min(peers)
                depth += line.x - x > INDENT_GAP
            else:
                depth = 0
        out.append(depth)
    return out


# levels: size and weight first, then title numbers when most entries have one, else the indent
def levels(parsed: list[tuple[Entry, pdf.Line, int]]) -> tuple[list[Entry], str]:
    style = _styles([(e, line) for e, line, _ in parsed])
    by_numbers = sum(_depth(e) is not None for e, _, _ in parsed) >= NUMBERED_SHARE * len(parsed)
    if by_numbers:
        inner = _depths(parsed)
    else:
        steps = _indent_steps([max(line.x, 0) for e, line, _ in parsed if e.printed is not None])
        inner = [steps[max(line.x, 0)] if e.printed is not None else 0 for e, line, _ in parsed]
    keys = []
    for (_, line, _), depth in zip(parsed, inner, strict=True):
        size, bold = style[(line.size, line.bold)]
        keys.append((-size, not bold, depth))
    rank = {k: i + 1 for i, k in enumerate(sorted(set(keys)))}
    for (entry, _, _), k in zip(parsed, keys, strict=True):
        entry.level = min(rank[k], 6)
    return [entry for entry, _, _ in parsed], "numbers" if by_numbers else "indent"


READER_PROMPT = (
    "You read the printed table of contents of a book and return JSON only, no prose: {\"entries\": [{\"title\": "
    "string, \"page\": the page number as printed or null, \"level\": 1 for the top level, 2 below it, and so on}]}. "
    "Keep the book's order and wording. Use only what the pages say."
)


def model_read(text: str) -> list[Entry]:
    import model_steps

    answer = model_steps.parse_json(model_steps.call("toc_reader", READER_PROMPT, text))
    out = []
    for item in answer.get("entries") or []:
        if not isinstance(item, dict) or not str(item.get("title") or "").strip():
            continue
        level = item.get("level")
        page = item.get("page")
        out.append(Entry(str(item["title"]).strip(), level if isinstance(level, int) and 1 <= level <= 6 else None,
                         printed=str(page) if page not in (None, "") else None, evidence="model read the contents"))
    return out


def read(files: list[BookFile], given: list[list[int]] | None) -> SourceToc:
    out = SourceToc("printed_contents")
    pages, lines = find_pages(files, given)
    out.notes["pages"] = pages
    lines = _without_watermarks(files, pages, lines)
    if not pages:
        out.failed = "no contents pages found" + ("" if given else " in the first and last pages")
        return out
    text = "\n".join(line.text for p in pages for line in lines.get(p, []))
    if not pdf.has_layer(text) or pdf.garbled(text):
        out.failed = f"contents pages {pages} have no readable text layer"
        return out
    parsed, others = parse(pages, lines, sum(f.pages for f in files))
    if others:
        out.notes["other_contents"] = others
    if sum(e.printed is not None for e, _, _ in parsed) >= conf()["contents"]["min_lines"]:
        out.entries, out.notes["levels_by"] = levels(parsed)
        out.notes["read_by"] = "parser"
        return out
    out.entries = model_read(text)
    out.notes["read_by"] = "model"
    if not out.entries:
        out.failed = f"neither the parser nor the model read entries on pages {pages}"
    return out
