# the contents pages printed in the book: lines ending in a page number, levels from their style and indent
import re
from collections import Counter

import numerals
import text_layer
from orm.catalogue import BookFile

from stages import running_heads
from stages.structure.sources import PRINTED_AHEAD, Entry, SourceEntries, book_lines, conf, pages_of, windows
from stages.structure.sources.numbering import title_depth

LEADER = r"(?:\s*(?:\.\s?|·\s?|…|_){2,}\s*|\s{2,}|\s)"
ENTRY = re.compile(rf"^(?P<title>.*?\S){LEADER}(?P<page>{numerals.PAGE})$", re.I)
DOTTED = re.compile(rf"(?:\.\s?|·\s?|…){{3,}}\s*{numerals.PAGE}$", re.I)
TRAILING_LEADER = re.compile(r"[\s.·…_]+$")
INDENT_GAP = 5
NUMBERED_SHARE = 0.5
READ_AHEAD = 20
# a contents' numbers mostly rise, reach across a third of the book, and start again only where another list does
CONTENTS_RISING = 0.7
CONTENTS_REACH = 3
CONTENTS_FALL = 0.1
# a block repeating at least a third of the contents' titles is the contents again, briefer or one node's
SHARED = 3
WATERMARK_SAMPLE = 40
WATERMARK_SHARE = 0.6
FOLIO = re.compile(rf"^\s*{numerals.PAGE}\s*$", re.I)
JOIN_SLACK = 3
# a page number with no leader, a mark that is no dash (a dash between numbers is a range), the next row's title
ROW_MARK = re.compile(r"(?<=[^\s.·…_])\s+(\d{1,4})\s+([^\w\s.,:;()'\"’“”‐\-–—])\s+(?=\w)")
ROW_MARK_LINES = 3
LONE_LABEL = re.compile(r"^\(?(?:[IVXLC]+|[A-Za-z]{1,2}|\d{1,3})[.)]\)?$")


def _numbered(lines: list[text_layer.Line]) -> int:
    return sum(bool(ENTRY.match(line.text)) for line in lines)


def _is_dotted(lines: list[text_layer.Line]) -> bool:
    return sum(bool(DOTTED.search(line.text)) for line in lines) >= conf()["contents"]["min_lines"]


# an entry's Arabic page inside the book (a postal box, a year are not pages); Roman pages count as entries only
def _pages_on(lines: list[text_layer.Line], total: int) -> tuple[list[int], int]:
    arabic, entries = [], 0
    for line in lines:
        m = ENTRY.match(line.text)
        if not m:
            continue
        page = m.group("page")
        if not page.isdigit():
            entries += 1
        elif 1 <= int(page) <= total + PRINTED_AHEAD:
            arabic.append(int(page))
            entries += 1
    return arabic, entries


# a contents points forward through the book: its pages' numbers rise, stay inside it and reach across a third of it
def _contents_like(numbers: list[int], total: int) -> bool:
    if len(set(numbers)) < conf()["contents"]["min_lines"]:
        return False
    rising = sum(b >= a for a, b in zip(numbers, numbers[1:], strict=False))
    return rising >= CONTENTS_RISING * (len(numbers) - 1) and (max(numbers) - min(numbers)) * CONTENTS_REACH >= total


# contents by shape, no heading word: runs of pages listing entries, cut where the numbers start again, judged whole
def _contents_pages(files: list[BookFile], lines: dict[int, list[text_layer.Line]]) -> list[int]:
    total = sum(f.pages for f in files)
    need = conf()["contents"]["min_lines"]
    numbered = {}
    for p in sorted(lines):
        arabic, entries = _pages_on(lines[p], total)
        if entries >= need:
            numbered[p] = arabic
    pieces, piece = [], []
    for p, arabic in numbered.items():
        restarts = piece and arabic and piece[-1][1] and arabic[0] < piece[-1][1][-1] - CONTENTS_FALL * total
        if piece and (p != piece[-1][0] + 1 or restarts):
            pieces.append(piece)
            piece = []
        piece.append((p, arabic))
    pieces += [piece] if piece else []
    found = [p for p in sorted(lines) if _is_dotted(lines[p])]
    for piece in pieces:
        if _contents_like([n for _, arabic in piece for n in arabic], total):
            found += [p for p, _ in piece]
    found = sorted(set(found))
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
def find_pages(files: list[BookFile],
               given: list[list[int]] | None) -> tuple[list[int], dict[int, list[text_layer.Line]]]:
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


# by place on the page, not by the layer's order: a heading set first may come out last
def _first_line(page_lines: list[text_layer.Line]) -> text_layer.Line | None:
    return min((x for x in page_lines if not FOLIO.match(x.text)), key=lambda x: (x.top, x.x), default=None)


def _last_line(page_lines: list[text_layer.Line]) -> text_layer.Line | None:
    return max((x for x in page_lines if not FOLIO.match(x.text)), key=lambda x: (x.top, x.x), default=None)


# a number far from the page it is printed on is an entry's page, not the page's folio
def _far_number(line: text_layer.Line, page: int) -> bool:
    m = ENTRY.match(line.text)
    return bool(m) and m.group("page").isdigit() and abs(int(m.group("page")) - page) > PRINTED_AHEAD


# the line topping two or more contents pages once their folios are cut is the running head, whatever it says
def _running_heads(pages: list[int], lines: dict[int, list[text_layer.Line]]) -> set[str]:
    tops = Counter(_without_page_number(first.text) for p in pages
                   if (first := _first_line(lines.get(p, []))) and not _far_number(first, p))
    return {text for text, n in tops.items() if n >= 2 and text}


# an edge line pointing at the very page it is printed on points at the contents itself: the page's folio line
def _own_folio(line: text_layer.Line, page: int) -> bool:
    m = ENTRY.match(line.text)
    return bool(m) and m.group("page").isdigit() and int(m.group("page")) == page


# a line printed on most pages of the book (a download stamp, a licence line) is never an entry
def _without_watermarks(files: list[BookFile], pages: list[int], lines: dict[int, list[text_layer.Line]]) -> dict:
    total = sum(f.pages for f in files)
    sample = book_lines(files, set(range(1, total + 1, max(1, total // WATERMARK_SAMPLE))))
    seen = Counter(text for page_lines in sample.values() for text in {x.text.strip() for x in page_lines})
    marks = {text for text, n in seen.items() if n >= WATERMARK_SHARE * len(sample) and len(sample) >= 5}
    return {p: [x for x in lines.get(p, []) if x.text.strip() not in marks] for p in pages}


def _running_head(line: text_layer.Line, page_lines: list[text_layer.Line], repeated: set[str], page: int) -> bool:
    if (line is _first_line(page_lines) or line is _last_line(page_lines)) and _own_folio(line, page):
        return True
    return line is _first_line(page_lines) and not _far_number(line, page) and \
        _without_page_number(line.text) in repeated


# centred lines without page numbers (a part title over two lines) join whatever their indent
def _continues(pending: text_layer.Line, line: text_layer.Line, numbered: bool) -> bool:
    return (pending.size, pending.bold) == (line.size, line.bold) and (not numbered or line.x >= pending.x - JOIN_SLACK)


# a wrapped title keeps its style and indent; a line breaking that ends the title above it
def _entries(page: int, lines: list[text_layer.Line]) -> list[tuple[Entry, text_layer.Line]]:
    out, pending = [], []
    for line in lines:
        # a wrapped row may come out as its title lines, then its label alone, then its page number alone
        if FOLIO.match(line.text) and len(pending) > 1 and LONE_LABEL.match(pending[-1].text):
            title = " ".join([pending[-1].text, *(x.text for x in pending[:-1])])
            out.append((Entry(title, None, printed=line.text.strip(), evidence=f"contents page {page}"), pending[-1]))
            pending = []
            continue
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
def _indented(entries: list[tuple[Entry, text_layer.Line, int]]) -> list[tuple[Entry, text_layer.Line, int]]:
    numbered = [(e, line, page) for e, line, page in entries if e.printed is not None]
    top = min((title_depth(e.title) or 0 for e, _, _ in numbered), default=0)
    own, parity = {}, {}
    for e, line, page in numbered:
        own[page] = min(own.get(page, line.x), line.x)
        if (title_depth(e.title) or 0) == top:
            parity[page % 2] = min(parity.get(page % 2, line.x), line.x)
    tops = {page for e, _, page in numbered if (title_depth(e.title) or 0) == top}
    edge = {page: own[page] if page in tops else parity.get(page % 2, own[page]) for page in own}
    return [(e, text_layer.Line(line.text, line.x - edge.get(page, line.x), line.top, line.size, line.bold), page)
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


# the book's own contents covers the book; a node's contents beside it covers that node, however many lines
def _reach(block: list, total: int) -> tuple[int, int]:
    numbers = _pages_of(block, total)
    return (max(numbers) - min(numbers) if numbers else 0, sum(e.printed is not None for e, _, _ in block))


# a year in a footnote is not a page: printed numbers run past the PDF's pages by the front matter at most
def _pages_of(block: list, total: int) -> list[int]:
    numbers = [int(e.printed) for e, _, _ in block if e.printed is not None and str(e.printed).isdigit()]
    return [n for n in numbers if n <= total + PRINTED_AHEAD]


# a block whose numbers go on from the last one's is the same contents; one starting again is a node's own
def _continued(blocks: list[list], total: int) -> list[list]:
    out: list[list] = []
    for block in blocks:
        before, now = (_pages_of(out[-1], total) if out else []), _pages_of(block, total)
        if before and now and now[0] >= before[-1]:
            out[-1] = out[-1] + block
        else:
            out.append(block)
    return out


def _starts_again(block: list, page_lines: list[text_layer.Line], total: int) -> bool:
    before, now = _pages_of(block, total), _pages_on(page_lines, total)[0]
    return bool(before and now) and now[0] < before[-1] - CONTENTS_FALL * total


# a mark the book sets after a page number at least a few times splits its rows run together on one line
def _row_mark(lines: list[text_layer.Line]) -> str | None:
    marks = Counter(m.group(2) for line in lines for m in ROW_MARK.finditer(line.text))
    mark, n = marks.most_common(1)[0] if marks else (None, 0)
    return mark if n >= ROW_MARK_LINES else None


# each row keeps its page number; a tail without one is a title wrapped onto the next line
def _rows(line: text_layer.Line, mark: str | None) -> list[text_layer.Line]:
    cuts = [m for m in ROW_MARK.finditer(line.text) if m.group(2) == mark] if mark else []
    tail = re.search(r"\s(\d{1,4})$", line.text)
    numbers = [int(m.group(1)) for m in cuts] + ([int(tail.group(1))] if tail else [])
    if not cuts or numbers != sorted(numbers):
        return [line]
    starts = [0, *(m.end() for m in cuts)]
    ends = [*(m.start(2) for m in cuts), len(line.text)]
    return [text_layer.Line(line.text[a:b].strip(), line.x, line.top, line.size, line.bold)
            for a, b in zip(starts, ends, strict=True)]


def parse(pages: list[int], lines: dict[int, list[text_layer.Line]],
          total: int) -> tuple[list[tuple[Entry, text_layer.Line, int]], list[list]]:
    blocks: list[list] = [[]]
    running = _running_heads(pages, lines)
    sizes = Counter(x.size for p in pages for x in lines.get(p, []) if ENTRY.match(x.text))
    body = sizes.most_common(1)[0][0] if sizes else 0
    last_page = None
    mark = _row_mark([x for p in pages for x in lines.get(p, [])])
    for p in pages:
        page_lines = []
        for x in lines.get(p, []):
            labelled = bool(page_lines) and LONE_LABEL.match(page_lines[-1].text) is not None
            if not _running_head(x, lines[p], running, p) and (labelled or not FOLIO.match(x.text)):
                page_lines += _rows(x, mark)
        # a list after the contents (of tables, of cases) starts on its own page and starts its numbers again
        opens = not blocks[-1] or p != last_page + 1 or _starts_again(blocks[-1], page_lines, total)
        if blocks[-1] and opens:
            blocks.append([])
        # a block's first line set larger than its entries, with no page number, is its heading ("Contents")
        head = _first_line(page_lines)
        if opens and head is not None and not ENTRY.match(head.text) and head.size > body:
            page_lines = [x for x in page_lines if x is not head]
        last_page = p
        blocks[-1] += [(e, line, p) for e, line in _entries(p, page_lines)]
    blocks = [_indented(b) for b in _continued([b for b in blocks if b], total)]
    if not blocks:
        return [], []
    fullest = max(blocks, key=lambda b: _reach(b, total))
    return _headings_only(fullest), [b for b in blocks if b is not fullest]


# a line without a page number is a title only when set larger than the entries, so the imprint drops
def _headings_only(block: list[tuple[Entry, text_layer.Line, int]]) -> list[tuple[Entry, text_layer.Line, int]]:
    sizes = Counter(line.size for e, line, _ in block if e.printed is not None)
    if not sizes:
        return block
    body = sizes.most_common(1)[0][0]
    return [(e, line, p) for e, line, p in block if e.printed is not None or line.size > body]


# a style seen once (a stray bold line) merges into the closest common one by size
def _styles(parsed: list[tuple[Entry, text_layer.Line]]) -> dict[tuple, tuple]:
    seen = Counter((line.size, line.bold) for _, line in parsed)
    common = [s for s, n in seen.items() if n >= 2] or list(seen)
    return {s: s if s in common else min(common, key=lambda c: (abs(c[0] - s[0]), c[1] != s[1])) for s in seen}


def _depth(entry: Entry) -> int | None:
    return title_depth(entry.title, bare=True)


# an unnumbered entry is as deep as the nearest numbered one on its page, deeper if clearly indented
def _depths(parsed: list[tuple[Entry, text_layer.Line, int]]) -> list[int]:
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
def levels(parsed: list[tuple[Entry, text_layer.Line, int]]) -> tuple[list[Entry], str]:
    style = _styles([(e, line) for e, line, _ in parsed])
    # rows split out of one printed line count as that line
    printed = {(page, line.top, line.x): e for e, line, page in reversed(parsed)}
    by_numbers = sum(_depth(e) is not None for e in printed.values()) >= NUMBERED_SHARE * len(printed)
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
        entry.level = rank[k]
    return [entry for entry, _, _ in parsed], "numbers" if by_numbers else "indent"


READER_PROMPT = (
    "You read the printed table of contents of a book and return JSON only, no prose: {\"entries\": [{\"title\": "
    "string, \"page\": the page number as printed or null, \"level\": 1 for the top level, 2 below it, and so on}]}. "
    "Keep the book's order and wording. Use only what the pages say."
)


def model_read(text: str) -> list[Entry]:
    import model_steps

    answer = model_steps.parse_json(model_steps.call("contents_reader", READER_PROMPT, text))
    out = []
    for item in answer.get("entries") or []:
        if not isinstance(item, dict) or not str(item.get("title") or "").strip():
            continue
        level = item.get("level")
        page = item.get("page")
        out.append(Entry(str(item["title"]).strip(), level if isinstance(level, int) and level >= 1 else None,
                         printed=str(page) if page not in (None, "") else None, evidence="model read the contents"))
    return out


def read(files: list[BookFile], given: list[list[int]] | None) -> SourceEntries:
    out = SourceEntries("printed_contents")
    pages, lines = find_pages(files, given)
    out.notes["pages"] = pages
    lines = _without_watermarks(files, pages, lines)
    if not pages:
        out.failed = "no contents pages found" + ("" if given else " in the first and last pages")
        return out
    text = "\n".join(line.text for p in pages for line in lines.get(p, []))
    if not text_layer.has_layer(text) or text_layer.garbled(text):
        out.failed = f"contents pages {pages} have no readable text layer"
        return out
    parsed, others = parse(pages, lines, sum(f.pages for f in files))
    if others:
        out.notes["other_contents"] = [len(b) for b in others]
    # pages before the winning block and blocks sharing its titles stay skipped; a list after it gives its pages back
    if parsed:
        titles = {running_heads.norm(e.title) for e, _, _ in parsed}
        kept = {p for _, _, p in parsed}
        for block in others:
            if sum(running_heads.norm(e.title) in titles for e, _, _ in block) * SHARED >= len(block):
                kept |= {p for _, _, p in block}
        out.notes["pages"] = [p for p in pages if p in kept or p < min(kept)]
        out.notes["pages_found"] = pages
    if sum(e.printed is not None for e, _, _ in parsed) >= conf()["contents"]["min_lines"]:
        out.entries, out.notes["levels_by"] = levels(parsed)
        out.notes["read_by"] = "parser"
        return out
    out.entries = model_read(text)
    out.notes["read_by"] = "model"
    if not out.entries:
        out.failed = f"neither the parser nor the model read entries on pages {pages}"
    return out
