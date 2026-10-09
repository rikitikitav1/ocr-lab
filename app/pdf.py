# thin helpers over pypdfium2; a book is one or more files with pages numbered across them
import functools
import re
import threading
from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium

# PDFium is not thread-safe, and the CPU lane runs several threads
_PDFIUM = threading.RLock()


def _serialised(fn):
    @functools.wraps(fn)
    def wrap(*args, **kwargs):
        with _PDFIUM:
            return fn(*args, **kwargs)

    return wrap

# fewer letters than this and the page is read as having no text layer; a recogniser that lost its
# alphabet leaves punctuation and digits behind, which must not pass for text
LAYER_MIN_LETTERS = 40
LAYER_RULE = "letters>=40"


@dataclass(frozen=True)
class BookPage:
    number: int
    file_ord: int
    file_page: int
    path: Path


@_serialised
def page_count(path: Path) -> int:
    doc = pdfium.PdfDocument(str(path))
    try:
        return len(doc)
    finally:
        doc.close()


@_serialised
def page_texts(path: Path, pages: list[int] | None = None) -> dict[int, str]:
    doc = pdfium.PdfDocument(str(path))
    try:
        wanted = range(len(doc)) if pages is None else [p for p in pages if 0 <= p < len(doc)]
        out = {}
        for i in wanted:
            page = doc[i]
            textpage = page.get_textpage()
            out[i] = repair(textpage.get_text_range())
            textpage.close()
            page.close()
        return out
    finally:
        doc.close()


# Cyrillic stored as cp1251 but read as Latin-1 ("Áîãäàí" for "Богдан"), seen on a cover's layer
MOJIBAKE = re.compile(r"[\u00c0-\u00ff][\u00c0-\u00ff\s.,:;!?\-]{2,}")


def repair(text: str) -> str:
    def fix(m):
        try:
            fixed = m.group(0).encode("latin-1").decode("cp1251")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return m.group(0)
        cyrillic = sum("\u0400" <= c <= "\u04ff" for c in fixed)
        return fixed if cyrillic >= sum(c.isalpha() for c in fixed) * 0.8 else m.group(0)

    return MOJIBAKE.sub(fix, text)


def letters(text: str) -> int:
    return sum(c.isalpha() for c in text)


def has_layer(text: str) -> bool:
    return letters(text) >= LAYER_MIN_LETTERS


# text is there but almost no letters: a broken layer, recognised again rather than trusted
def garbled(text: str) -> bool:
    printable = sum(c.isprintable() and not c.isspace() for c in text)
    return printable >= LAYER_MIN_LETTERS and not has_layer(text)


@_serialised
def outline(path: Path) -> list[dict]:
    doc = pdfium.PdfDocument(str(path))
    try:
        out = []
        for item in doc.get_toc(max_depth=15):
            dest = item.get_dest()
            index = dest.get_index() if dest is not None else None
            out.append({"title": item.get_title().strip(), "level": item.level + 1, "page": index})
        return out
    finally:
        doc.close()


@_serialised
def info(path: Path) -> dict:
    doc = pdfium.PdfDocument(str(path))
    try:
        return {k: v for k, v in doc.get_metadata_dict().items() if v}
    finally:
        doc.close()
