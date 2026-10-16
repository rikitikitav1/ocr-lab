# headings found by their numbers in the text: part and chapter labels, Roman chapter numbers, 1.2.3 sections
import re
from collections import Counter
from functools import cache

import numerals
from orm.catalogue import BookFile

from stages.structure.sources import Entry, SourceEntries, book_lines, conf

DOTTED = re.compile(r"^(?P<num>\d{1,2}(?:\.\d{1,3}){1,4})\.?\s*(?P<title>[^\W\d_].*)$")
ROMAN_TITLED = re.compile(rf"^(?P<num>{numerals.ROMAN_LABEL_UPPER})\.\s+(?P<title>[^\W\d_].*)$")
ROMAN_ALONE = re.compile(rf"^(?P<num>{numerals.ROMAN_LABEL_UPPER})\.?$")
MAX_TITLE_WORDS = 15


@cache
def label_pattern(kind: str) -> re.Pattern:
    words = "|".join(re.escape(w) for w in conf()["text_layer"]["numbering"][kind])
    if not words:
        return re.compile(r"(?!)")
    # a number in words is any word ("Part One", "part one"), so "Part of Speech" reads as a part too
    number = rf"\d{{1,3}}|{numerals.ROMAN_LABEL}|\w+"
    return re.compile(rf"^(?P<label>{words})\s+(?P<num>{number})\b[.:]?\s*(?P<title>.*)$", re.I)


BARE = re.compile(r"^\d{1,3}\.?\s+[^\W\d_]")


# depth of a heading's own number: -1 part, 0 chapter, 1 for 1.2; a bare "3 Types" counts only if bare
def title_depth(title: str, bare: bool = False) -> int | None:
    text = title.strip()
    if label_pattern("part").match(text):
        return -1
    if label_pattern("chapter").match(text):
        return 0
    if m := DOTTED.match(text):
        return m.group("num").count(".")
    return 0 if bare and BARE.match(text) else None


# a label opens a part or chapter only in a heading style or alone on its line, so prose stays prose
def _match(text: str, head: bool, set_apart: bool) -> tuple[str, tuple, str] | None:
    if head:
        for kind in ("part", "chapter"):
            if m := label_pattern(kind).match(text):
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


def _body_style(lines: dict) -> tuple[float, bool]:
    styles = Counter()
    for page_lines in lines.values():
        for line in page_lines:
            styles[(line.size, line.bold)] += len(line.text)
    return styles.most_common(1)[0][0] if styles else (0, False)


# some fonts report every weight as bold, and then bold sets nothing apart from the body
def _set_apart(line, body: tuple[float, bool]) -> bool:
    size, bold = body
    return (line.bold and not bold) or line.size > size + 0.5


def _plausible(text: str) -> bool:
    return len(text) <= conf()["text_layer"]["numbering"]["max_chars"] and len(text.split()) <= MAX_TITLE_WORDS + 3


def _candidates(lines: dict, skip_pages: set[int]) -> list[tuple[str, tuple, str, int]]:
    head_lines = conf()["text_layer"]["numbering"]["head_lines"]
    body = _body_style(lines)
    out = []
    for page in sorted(lines):
        if page in skip_pages:
            continue
        page_lines = lines[page]
        for i, line in enumerate(page_lines):
            text = line.text.strip()
            if not _plausible(text) or (hit := _match(text, i < head_lines, _set_apart(line, body))) is None:
                continue
            kind, key, title = hit
            after = page_lines[i + 1] if i + 1 < len(page_lines) else None
            if not title and after is not None and _plausible(after.text) and _set_apart(after, body):
                title = after.text.strip()
            out.append((kind, key, text if not title or title in text else f"{text} {title}", page))
    return out


# a number met again, stepping back, or outside its chapter is a running head or a reference
def read(files: list[BookFile], skip_pages: set[int], lines: dict | None = None) -> SourceEntries:
    out = SourceEntries("numbering")
    found = _candidates(lines if lines is not None else book_lines(files), skip_pages)
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
        out.entries.append(Entry(title, min(level, 6), page,
                                 evidence=f"{label}{kind} number {'.'.join(map(str, key))}", verified=True))
    if not out.entries:
        out.failed = "no numbered headings in the text"
    return out
