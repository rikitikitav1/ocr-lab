import re

# a scan's contents: MinerU's index blocks are the entries and its page numbers give the offset
from collections import Counter

import artifacts
import numerals
import settings
from job_signals import Deferred
from orm.catalogue import Book
from rapidfuzz import fuzz

from stages import intake, running_heads
from stages.toc import pages as placing
from stages.toc.sources import PRINTED_AHEAD, Entry, SourceToc, conf, pages_of, windows
from stages.toc.sources.numbering import title_depth
from stages.toc.sources.printed_contents import ENTRY, TRAILING_LEADER, _heading_words

STAGE = "toc"
FIELDS = [("tier", "standard"), ("ocr_mode", "ocr"), ("output_formats", ["middle_json"])]
CHUNK = 30
MIN_FOLIOS = 3
HEADING_LIKE = 85
# a contents page's numbers rise; misread digits and front matter in Roman leave some steps back, a table many
CONTENTS_RISING = 0.7


def is_scan(book: Book) -> bool:
    layer = book.text_layer or {}
    # a plate is both without a layer and garbled, and counts once
    unreadable = set(layer.get("without_layer", [])) | set(layer.get("garbled", []))
    return len(unreadable) * 2 > (book.pages or 0)


# the start of the book is recognised first, its end only when the start holds no contents
def contents_window(book_id: int, files, given: list[list[int]] | None,
                    cached_only: bool = False) -> dict[int, dict] | None:
    if given:
        return recognise(book_id, pages_of(given), cached_only)
    head, tail = windows(sum(f.pages for f in files))
    recognised = recognise(book_id, head, cached_only)
    if recognised is None or entries(recognised, sum(f.pages for f in files))[0] or not tail:
        return recognised
    rest = recognise(book_id, tail, cached_only)
    return None if rest is None else {**recognised, **rest}


def _runs(book_pages: list[int], files) -> list[tuple]:
    out = []
    for f in files:
        inside = [p - f.first_page + 1 for p in book_pages if f.first_page <= p < f.first_page + f.pages]
        start = None
        for i, p in enumerate(inside):
            if start is None:
                start = p
            last_of_run = i + 1 == len(inside) or inside[i + 1] != p + 1 or p - start + 1 == CHUNK
            if last_of_run:
                out.append((f, start, p))
                start = None
    return out


def _kept_name(f, a: int, b: int) -> str:
    return f"contents_ocr.{f.ord}.{a}-{b}.json"


def kept_names(book_id: int, book_pages: list[int]) -> list[str]:
    return [_kept_name(f, a, b) for f, a, b in _runs(book_pages, intake.files_of(book_id))]


# each chunk is read once and kept; `cached_only` lets a CPU job use what the GPU lane recognised
def recognise(book_id: int, book_pages: list[int], cached_only: bool = False) -> dict[int, dict] | None:
    from engines import converter_tools, reading

    files = intake.files_of(book_id)
    owner = artifacts.Owner(book_id=book_id)
    try:
        build = reading.build("mineru")
    except Deferred:
        if cached_only:
            return None
        raise
    out = {}
    for f, a, b in _runs(book_pages, files):
        made_from = artifacts.Inputs({"stage": "toc_ocr", "file": f.sha256, "pages": [a, b], "fields": FIELDS,
                                      "build": build})
        name = _kept_name(f, a, b)
        done = artifacts.find_done(owner, STAGE, name, made_from.key)
        if done is not None:
            layout = converter_tools.kept_json(done)
        elif cached_only:
            return None
        else:
            layout = reading.read("mineru", settings.DATA_DIR / f.file_path, a, b, FIELDS, 1800, build)
            artifacts.write(owner, artifacts.book_dir(book_id), STAGE, name, layout, made_from,
                            meta={"engine": "mineru", "build": build, "fields": FIELDS})
        # MinerU numbers pages from the start of the file, not of the range it read
        for page in (p for part in reading.parts(layout) for p in part.get("pages", [])):
            out[f.first_page + page["page_idx"]] = page
    return out


# every page of a scan recognised (kept like the contents windows), and the blocks starting in its top part
def top_blocks(book_id: int, total: int) -> dict[int, list[str]]:
    top = conf()["labels"]["top_share"]
    return {page: [" ".join(_text(b).split()) for b in layout.get("blocks", []) if b.get("bbox") and b["bbox"][1] < top]
            for page, layout in recognise(book_id, list(range(1, total + 1))).items()}


def _text(node) -> str:
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return " ".join(_text(x) for x in node)
    if isinstance(node, dict):
        return _text(node.get("content"))
    return ""


def _blocks(page: dict, kind: str) -> list[dict]:
    return [b for b in page.get("blocks", []) if b.get("type") == kind]


# a contents heading, read with a letter lost ("ОЛАВЛЕНИЕ"), is no part of the first entry
def _without_heading(text: str) -> str:
    words = text.split()
    if words and max(fuzz.ratio(running_heads.norm(words[0]), h) for h in _heading_words()) >= HEADING_LIKE:
        return " ".join(words[1:])
    return text


# a line without a page number opens the next entry, unless the next line says it again (a page heading)
def _joined(pending: str, text: str) -> str:
    pending = _without_heading(pending)
    if pending and running_heads.norm(text).startswith(running_heads.norm(pending)):
        return text
    return f"{pending} {text}".strip()


# an entry's page number after a leader, or in brackets at the end of its description: "... лазер (46)"
BRACKETED = re.compile(r"^(?P<title>.*?\S)\s*\((?P<page>\d{1,4})\)\s*$")


def _entry(text: str):
    return ENTRY.match(text) or BRACKETED.match(text)


def _numbers(items: list) -> list[int]:
    found = [_entry(" ".join(_text(item).split())) for item in items]
    return [int(m.group("page")) for m in found if m is not None and m.group("page").isdigit()]


TEXT_BLOCKS = ("text", "title", "doc_title", "paragraph_title")
# a contents set as prose reaches across the book; a numbered table or exercise covers a stretch of it
PROSE_REACH = 3


def _spans_book(numbers: list[int], total: int) -> bool:
    return len(numbers) >= conf()["contents"]["min_lines"] and (max(numbers) - min(numbers)) * PROSE_REACH >= total


# the engine's index blocks, or, on a page it did not mark so, its text blocks in order (a contents set as prose)
def _items(page: dict) -> list:
    index = [item for block in _blocks(page, "index") for item in block.get("content", [])]
    return index or [b for b in page.get("blocks", []) if b.get("type") in TEXT_BLOCKS]


# contents point forward through the book: a numbered list whose numbers jump back or past the end is a table
def _contents_like(numbers: list[int], total: int) -> bool:
    if not numbers:
        return False
    rising = sum(b >= a for a, b in zip(numbers, numbers[1:], strict=False))
    return max(numbers) <= total + PRINTED_AHEAD and rising >= CONTENTS_RISING * (len(numbers) - 1)


# index items in order; an item without a page number is the first line of a wrapped title
def entries(recognised: dict[int, dict], total: int) -> tuple[list[Entry], list[int]]:
    out, pending, contents_pages = [], "", []
    for page in sorted(recognised):
        items = _items(recognised[page])
        numbers = _numbers(items)
        # text blocks are any page's prose, so they need as many numbered lines as a contents in the layer does
        prose = not _blocks(recognised[page], "index")
        if not _contents_like(numbers, total) or (prose and not _spans_book(numbers, total)):
            continue
        contents_pages.append(page)
        for item in items:
            text = " ".join(_text(item).split())
            m = _entry(text)
            if m is None or not m.group("page").isdigit():
                pending = _joined(pending, text)
                continue
            title = TRAILING_LEADER.sub("", f"{pending} {m.group('title')}".strip()).strip()
            pending = ""
            if title:
                out.append(Entry(title, None, printed=m.group("page"), evidence=f"recognised contents page {page}"))
    return out, contents_pages


# a title's numbering style, read from its shape alone: Roman, Arabic by its dots, a letter, or a labelled part
STYLE_ROMAN = re.compile(rf"^{numerals.ROMAN_LABEL_UPPER}[.)]\s")
# a one-letter "C." or "V." is a letter in a run A. B. C. unless the list also holds a longer Roman numeral
LONG_ROMAN = re.compile(rf"^(?=[IVXLC]{{2}}){numerals.ROMAN_LABEL_UPPER}[.)]\s")
STYLE_LETTER = re.compile(r"^[^\W\d_][.)]\s")


# a word repeated before numbers ("CAPITOLUL I.", "CAPITOLUL II.") labels a style in any language
STYLE_LABELLED = re.compile(rf"^([^\W\d_]{{3,}})\s+(?:{numerals.ROMAN_LABEL_UPPER}|\d{{1,3}})\b[.:]?(?:\s|$)")


def labels(titles: list[str]) -> set[str]:
    words = Counter(m.group(1).lower() for t in titles if (m := STYLE_LABELLED.match(t.strip())))
    return {w for w, n in words.items() if n >= 2}


def style(title: str, labelled: set[str] = frozenset(), roman: bool = True) -> tuple | None:
    text = title.strip()
    if (m := STYLE_LABELLED.match(text)) and m.group(1).lower() in labelled:
        return ("label", m.group(1).lower())
    depth = title_depth(text, bare=True)
    if depth == -1:
        return ("part",)
    if STYLE_ROMAN.match(text) and (roman or LONG_ROMAN.match(text)):
        return ("roman",)
    if depth is not None:
        return ("arabic", depth)
    if STYLE_LETTER.match(text):
        return ("letter", text[0].isupper())
    return None


# the first numbering style met is outermost, a new one nests, an old one climbs back; unnumbered sits innermost
def levels(found: list[Entry]) -> None:
    open_styles: list[tuple] = []
    labelled = labels([e.title for e in found])
    roman = any(LONG_ROMAN.match(e.title.strip()) for e in found)
    for e in found:
        found_style = style(e.title, labelled, roman)
        if found_style is None:
            e.level = min(len(open_styles) + 1, 6)
            continue
        if found_style in open_styles:
            del open_styles[open_styles.index(found_style) + 1:]
        else:
            open_styles.append(found_style)
        e.level = min(len(open_styles), 6)


def folio_offset(recognised: dict[int, dict]) -> tuple[int | None, int]:
    seen = Counter()
    for page, layout in recognised.items():
        for block in _blocks(layout, "page_number"):
            number = _text(block).strip()
            if number.isdigit():
                seen[page - int(number)] += 1
    if not seen:
        return None, 0
    offset, votes = seen.most_common(1)[0]
    return (offset, votes) if votes >= MIN_FOLIOS else (None, votes)


# a text book without contents in its text layer: the raster is read, entries placed through the text
def raster_contents(book_id: int, given: list[list[int]] | None, run: bool) -> SourceToc | None:
    files = intake.files_of(book_id)
    recognised = contents_window(book_id, files, given, cached_only=not run)
    if recognised is None:
        return None
    found, contents_pages = entries(recognised, sum(f.pages for f in files))
    levels(found)
    return SourceToc("printed_contents", found, failed=None if found else "no contents in the recognised pages",
                     notes={"pages": contents_pages, "read_by": "recognition of a text book"})


def read(book_id: int, given: list[list[int]] | None) -> tuple[SourceToc, dict]:
    files = intake.files_of(book_id)
    total = sum(f.pages for f in files)
    recognised = contents_window(book_id, files, given)
    found, contents_pages = entries(recognised, total)
    out = SourceToc("printed_contents", found, notes={"pages": contents_pages, "read_by": "recognition"})
    if not found:
        out.failed = "no contents in the recognised pages"
        return out, {}
    levels(found)
    offset, votes = folio_offset(recognised)
    if offset is None:
        out.failed = f"recognised contents, but too few page numbers to place them ({votes})"
        return out, {"offset": None, "offset_votes": votes}
    text = {p: placing.norm(" ".join(_text(b) for b in layout.get("blocks", []) if b.get("type") != "index"))
            for p, layout in recognised.items() if p not in contents_pages}
    verified = 0
    for e in found:
        e.page = min(max(int(e.printed) + offset, 1), total)
        e.verified = any(k in text.get(e.page, "") for k in placing.keys(e))
        verified += e.verified
    return out, {"offset": offset, "offset_votes": votes, "offset_from": "page numbers", "verified": verified,
                 "unverified": len(found) - verified, "unplaced": 0}
