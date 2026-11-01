# headings found by their numbers in the text: part and chapter labels, Roman chapter numbers, 1.2.3 sections
import re
from collections import Counter

import numerals
from elements import body as body_element
from orm.catalogue import BookFile

from stages.structure.sources import Entry, SourceEntries, book_lines, conf, series

DOTTED = re.compile(r"^(?P<num>\d{1,2}(?:\.\d{1,3}){1,4})\.?\s*(?P<title>[^\W\d_].*)$")
ROMAN_TITLED = re.compile(rf"^(?P<num>{numerals.ROMAN_LABEL_UPPER})\.\s+(?P<title>[^\W\d_].*)$")
ROMAN_ALONE = re.compile(rf"^(?P<num>{numerals.ROMAN_LABEL_UPPER})\.?$")
MAX_TITLE_WORDS = 15
FOLIO_SHARE = 0.5
SERIES_START = 3
RISING_SHARE = 0.7


# a word and its number at a line's start: a number in words is any word, so prose stays out by the rest of the rules
LABELLED_LINE = re.compile(
    rf"^(?P<label>[^\W\d_]{{3,}})\s+(?P<num>\d{{1,3}}|{numerals.ROMAN_LABEL}|\w+)\b[.:]?\s*(?P<title>.*)$", re.I)


# depth of a heading's own number: -1 part, 0 chapter by the book's labels, 1 for 1.2; "3 Types" only if bare
def title_depth(title: str, bare: bool = False, labels: dict[str, int] | None = None) -> int | None:
    text = title.strip()
    if labels and (word := series.label_of(text)) in labels:
        return labels[word]
    if m := DOTTED.match(text):
        return m.group("num").count(".")
    return 0 if bare and series.BARE.match(text) else None


# a label opens a part or chapter only in a heading style or alone on its line, so prose stays prose
def _match(text: str, head: bool, set_apart: bool, kinds: dict[str, str]) -> tuple[str, tuple, str] | None:
    if head:
        if (m := LABELLED_LINE.match(text)) and (kind := kinds.get(m.group("label").lower())):
            num, title = m.group("num"), m.group("title")
            value = numerals.value(num)
            alone = not title
            if (value is None and not alone) or not (set_apart or alone):
                return None
            return kind, (value or num.lower(),), title
        if (m := ROMAN_TITLED.match(text)) or (m := ROMAN_ALONE.match(text)):
            value = numerals.roman(m.group("num"))
            title = m.groupdict().get("title") or ""
            if value and (set_apart or not title):
                return "roman", (value,), title
    if (m := DOTTED.match(text)) and not m.group("title")[0].islower():
        return "section", tuple(int(x) for x in m.group("num").split(".")), m.group("title")
    return None


# some fonts report every weight as bold, and then bold sets nothing apart from the body
def _set_apart(line, body: tuple[float, bool]) -> bool:
    size, bold = body
    return (line.bold and not bold) or line.size > size + 0.5


def _plausible(text: str) -> bool:
    return len(text) <= conf()["text_layer"]["numbering"]["max_chars"] and len(text.split()) <= MAX_TITLE_WORDS + 3


# a word whose number keeps step with the pages is a running head: chapters' numbers do not
def _runs_with_pages(rows: list[tuple[int, str]]) -> bool:
    gaps = Counter(page - int(num) for page, num in rows if num.isdigit())
    return bool(gaps) and gaps.most_common(1)[0][1] > FOLIO_SHARE * len(rows)


# a chapter's or part's numbers start low and mostly rise: "exit 0" and a code line's numbers do not
def _a_series(rows: list[tuple[int, str]]) -> bool:
    values = [v for _, num in rows if (v := numerals.value(num)) is not None]
    if not values:
        return False
    # a label repeated over its chapter's pages counts once
    values = [v for i, v in enumerate(values) if not i or v != values[i - 1]]
    rising = sum(b > a for a, b in zip(values, values[1:], strict=False))
    return 1 <= values[0] <= SERIES_START and rising >= RISING_SHARE * (len(values) - 1)


# labels from the pages' heads, for a book with no contents: a word and a figure or Roman number, set apart or alone
def _kinds(lines: dict, skip_pages: set[int], body: tuple[float, bool], head_lines: int,
           band: frozenset[int] = frozenset()) -> dict[str, str]:
    heads: list[str] = []
    rows: dict[str, list[tuple[int, str]]] = {}
    for page in sorted(lines):
        if page in skip_pages:
            continue
        for line in lines[page][:head_lines]:
            text = line.text.strip()
            m = series.LABELLED.match(text)
            if id(line) in band or not m or not _plausible(text) or numerals.value(m["num"]) is None:
                continue
            if _set_apart(line, body) or len(text.split()) == 2:
                heads.append(text)
                rows.setdefault(m["word"].lower(), []).append((page, m["num"]))
    kept = [text for text in heads if not _runs_with_pages(rows[series.label_of(text)])
            and _a_series(rows[series.label_of(text)])]
    depths = series.label_depths(kept, bare=False)
    common = max(depths, key=lambda word: len(rows[word]), default=None)
    return {word: "part" if depth < 0 else "chapter" for word, depth in depths.items() if depth < 0 or word == common}


def _candidates(lines: dict, skip_pages: set[int],
                band: frozenset[int] = frozenset()) -> list[tuple[str, tuple, str, int]]:
    head_lines = conf()["text_layer"]["numbering"]["head_lines"]
    body = body_element.learn(lines, band)
    kinds = _kinds(lines, skip_pages, body, head_lines, band)
    out = []
    for page in sorted(lines):
        if page in skip_pages:
            continue
        page_lines = lines[page]
        for i, line in enumerate(page_lines):
            text = line.text.strip()
            if not _plausible(text) or (hit := _match(text, i < head_lines, _set_apart(line, body), kinds)) is None:
                continue
            kind, key, title = hit
            after = page_lines[i + 1] if i + 1 < len(page_lines) else None
            if not title and after is not None and _plausible(after.text) and _set_apart(after, body):
                title = after.text.strip()
            out.append((kind, key, text if not title or title in text else f"{text} {title}", page))
    return out


# a number met again, stepping back, or outside its chapter is a running head or a reference
def read(files: list[BookFile], skip_pages: set[int], lines: dict | None = None,
         band: frozenset[int] = frozenset()) -> SourceEntries:
    out = SourceEntries("numbering")
    found = _candidates(lines if lines is not None else book_lines(files), skip_pages, band)
    # a bare Roman number is a chapter only in books without labelled chapters; elsewhere it is a list item
    labelled = any(k == "chapter" for k, *_ in found)
    found = [(("chapter" if k == "roman" else k), *rest, k != "roman") for k, *rest in found
             if not (k == "roman" and labelled)]
    chapter_level = 2 if any(k == "part" for k, *_ in found) else 1
    taken, chapter, section = set(), None, None
    for kind, key, title, page, has_label in found:
        if (kind, key) in taken:
            continue
        numeric = all(isinstance(x, int) for x in key)
        if kind == "part":
            level, chapter = 1, None
        elif kind == "chapter":
            if numeric and chapter is not None and key <= chapter:
                continue
            level, chapter = chapter_level, key if numeric else chapter
        else:
            if section is not None and key <= section:
                continue
            if chapter is not None and key[0] != chapter[0]:
                continue
            if chapter is None and section is not None and key[0] > section[0] + 1:
                continue
            level, section = chapter_level + len(key) - 1, key
        taken.add((kind, key))
        # a bare "Chapter 4." alone on a line is a reference or a caption; a heading names itself
        named = len(title.split()) >= 3
        label = "labelled " if has_label and named and kind in ("part", "chapter") else ""
        out.entries.append(Entry(title, level, page,
                                 evidence=f"{label}{kind} number {'.'.join(map(str, key))}", verified=True))
    if not out.entries:
        out.failed = "no numbered headings in the text"
    return out
