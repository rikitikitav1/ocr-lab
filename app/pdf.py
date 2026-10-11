# thin helpers over pypdfium2; a book is one or more files with pages numbered across them
import functools
import html
import re
import statistics
import struct
import threading
import zlib
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_raw
import text_clean

# PDFium is not thread-safe, and the CPU lane runs several threads
_PDFIUM = threading.RLock()


def _serialised(fn):
    @functools.wraps(fn)
    def wrap(*args, **kwargs):
        with _PDFIUM:
            return fn(*args, **kwargs)

    return wrap

# fewer letters than this is no text layer: a recogniser that lost its alphabet leaves only digits
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


# the glyphs of a page as shares of the page from the top left, loose boxes so a comma sits on its line's row
@_serialised
def page_glyphs(path: Path, page_index: int) -> list[tuple[float, float, float, float, str]]:
    doc = pdfium.PdfDocument(str(path))
    try:
        page = doc[page_index]
        width, height = page.get_size()
        textpage = page.get_textpage()
        out = []
        for i in range(textpage.count_chars()):
            ch = textpage.get_text_range(i, 1)
            if not ch or ch in ("\r", "\n") or ch.isspace():
                continue
            left, bottom, right, top = textpage.get_charbox(i, loose=True)
            out.append((left / width, 1 - top / height, right / width, 1 - bottom / height,
                        "-" if ch == "\ufffe" else repair(ch)))
        textpage.close()
        page.close()
        return out
    finally:
        doc.close()


def _png(rows: list[bytes], width: int, height: int) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    raw = b"".join(b"\x00" + row for row in rows)
    head = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", head) + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")


# a box of a page, as shares from the top left, rendered to PNG at the given dots per inch
@_serialised
def page_crop(path: Path, page_index: int, box: tuple[float, float, float, float], dpi: int = 150) -> bytes:
    doc = pdfium.PdfDocument(str(path))
    try:
        page = doc[page_index]
        bitmap = page.render(scale=dpi / 72, rev_byteorder=True)
        width, height, stride, buffer = bitmap.width, bitmap.height, bitmap.stride, bytes(bitmap.buffer)
        channels = bitmap.n_channels
        page.close()
    finally:
        doc.close()
    left, top, right, bottom = (round(v * n) for v, n in zip(box, (width, height, width, height), strict=True))
    left, top = max(0, left), max(0, top)
    right, bottom = min(width, max(right, left + 1)), min(height, max(bottom, top + 1))
    rows = []
    for y in range(top, bottom):
        line = buffer[y * stride + left * channels:y * stride + right * channels]
        rows.append(line if channels == 3 else b"".join(line[i:i + 3] for i in range(0, len(line), channels)))
    return _png(rows, right - left, bottom - top)


# width and height of each page in points, by the page's index in the file
@_serialised
def page_sizes(path: Path) -> list[tuple[float, float]]:
    doc = pdfium.PdfDocument(str(path))
    try:
        return [doc[i].get_size() for i in range(len(doc))]
    finally:
        doc.close()


# one reading per page, the file opened once and every page closed after its reading
@_serialised
def _each_page(path: Path, pages: list[int] | None, read) -> dict:
    doc = pdfium.PdfDocument(str(path))
    try:
        wanted = range(len(doc)) if pages is None else [p for p in pages if 0 <= p < len(doc)]
        out = {}
        for i in wanted:
            page = doc[i]
            textpage = page.get_textpage()
            out[i] = read(page, textpage)
            textpage.close()
            page.close()
        return out
    finally:
        doc.close()


def page_texts(path: Path, pages: list[int] | None = None) -> dict[int, str]:
    return _each_page(path, pages, lambda page, textpage: repair(_joined(textpage)[0]))


@dataclass(frozen=True)
class Line:
    text: str
    x: float
    top: float
    size: float
    bold: bool


def _low(gaps: list[float]) -> float:
    return sorted(gaps)[len(gaps) * 3 // 10]


# PDFium breaks lines inside words whose glyphs sit on one row ("Север\r\nе уступае"), and such a break is undone
def _joined(textpage) -> tuple[str, list[int]]:
    text = textpage.get_text_range()
    if len(text) != textpage.count_chars():
        return text, list(range(len(text)))
    box: list = []
    for i, ch in enumerate(text):
        try:
            box.append(textpage.get_charbox(i) if ch.isalpha() else None)
        except pdfium.PdfiumError:
            box.append(None)
    drop = _breaks(text, box, [bool(pdfium_raw.FPDFText_IsGenerated(textpage.raw, i)) for i in range(len(text))])
    kept = [k for k in range(len(text)) if k not in drop]
    return "".join(text[k] for k in kept), kept


def join_breaks(text: str, box: list, made: list[bool]) -> str:
    drop = _breaks(text, box, made)
    return "".join(c for k, c in enumerate(text) if k not in drop)


# a break goes when its letters are no further apart than letters nearby plus a quarter glyph height
def _breaks(text: str, box: list, made: list[bool]) -> set[int]:
    n = len(text)
    row_of, row = [0] * n, 0
    for i, ch in enumerate(text):
        row += ch == "\n"
        row_of[i] = row

    # a recogniser's invisible layer may give glyphs no height; a letter is then about 1.4 widths tall
    def height(k: int) -> float:
        left, bottom, right, top = box[k]
        return top - bottom if top - bottom > 0.3 * (right - left) else 1.4 * (right - left)

    def same_row(a: int, b: int) -> bool:
        if box[a][3] <= box[a][1] or box[b][3] <= box[b][1]:
            return abs(box[a][1] - box[b][1]) < 0.3 * max(height(a), height(b))
        overlap = min(box[a][3], box[b][3]) - max(box[a][1], box[b][1])
        return overlap >= 0.5 * min(box[a][3] - box[a][1], box[b][3] - box[b][1])

    letters = [i for i in range(n) if box[i]]
    at = {k: j for j, k in enumerate(letters)}
    tight: dict[int, float] = {}
    for a, b in zip(letters, letters[1:], strict=False):
        if b == a + 1 and same_row(a, b):
            tight[a] = box[b][0] - box[a][2]
    page_gap = _low(list(tight.values())) if tight else 0.0
    drop = set()
    for a, b in zip(letters, letters[1:], strict=False):
        between = range(a + 1, b)
        if b == a + 1 or not any(text[k] == "\n" for k in between) or not same_row(a, b) \
                or not all(made[k] and text[k] in " \r\n" for k in between):
            continue
        h = max(height(a), height(b))
        # the letters' own gap is read near the pair in glyphs of its size, so another font on the page cannot set it
        near = [tight[k] for k in letters[max(0, at[a] - 5):at[b] + 5]
                if k in tight and abs(height(k) - h) < 0.2 * h and row_of[k] in (row_of[a], row_of[b])]
        own = statistics.median(near) if len(near) >= 2 else page_gap
        if box[b][0] > box[a][0] and box[b][0] - box[a][2] < own + 0.25 * h:
            drop.update(between)
    return drop


def _char_style(textpage, index: int) -> tuple[float, bool]:
    matrix = pdfium_raw.FS_MATRIX()
    pdfium_raw.FPDFText_GetMatrix(textpage.raw, index, matrix)
    scale = abs(matrix.d) or (matrix.b ** 2 + matrix.d ** 2) ** 0.5 or 1
    size = pdfium_raw.FPDFText_GetFontSize(textpage.raw, index) * scale
    return round(size * 2) / 2, pdfium_raw.FPDFText_GetFontWeight(textpage.raw, index) >= 600


# lines as PDFium breaks them less breaks inside a word; position from the first character, style from the most common
def _lines(page, textpage) -> list[Line]:
    height = page.get_height()
    text, char_at = _joined(textpage)
    out, offset = [], 0
    for raw_line in text.split("\r\n"):
        begin, offset = offset, offset + len(raw_line) + 2
        stripped = raw_line.strip()
        if not stripped:
            continue
        first = begin + (len(raw_line) - len(raw_line.lstrip()))
        try:
            left, _, _, top = textpage.get_charbox(char_at[first])
        except Exception:
            continue
        styles = Counter(_char_style(textpage, char_at[i]) for i in range(first, begin + len(raw_line.rstrip()))
                         if not raw_line[i - begin].isspace())
        (size, bold), _ = styles.most_common(1)[0]
        out.append(Line(repair(stripped), round(left, 1), round(height - top, 1), size, bold))
    return out


def page_lines(path: Path, pages: list[int] | None = None) -> dict[int, list[Line]]:
    return _each_page(path, pages, _lines)


# Cyrillic stored as cp1251 but read as Latin-1 ("Áîãäàí" for "Богдан"), seen on a cover's layer
MOJIBAKE = re.compile(r"[\u00c0-\u00ff][\u00c0-\u00ff\s.,:;!?\-]{2,}")


# cp1251 read as Latin-1 is repaired before cleaning, since its letters include the C1 range cleaning drops
def repair(text: str) -> str:
    return text_clean.clean(_cp1251(text))


def _cp1251(text: str) -> str:
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


# letters a font with a shifted encoding maps to: phonetic signs and private-use code points; no shelf book had any
SHIFTED_SHARE = 0.3


def _shifted(text: str) -> bool:
    found = [c for c in text if c.isalpha()]
    odd = sum(0x250 <= ord(c) <= 0x2AF or 0xE000 <= ord(c) <= 0xF8FF for c in found)
    return len(found) >= LAYER_MIN_LETTERS and odd >= SHIFTED_SHARE * len(found)


# almost no letters, or letters in a shifted encoding: a broken layer, recognised again rather than trusted
def garbled(text: str) -> bool:
    printable = sum(c.isprintable() and not c.isspace() for c in text)
    return (printable >= LAYER_MIN_LETTERS and not has_layer(text)) or _shifted(text)


@_serialised
def outline(path: Path) -> list[dict]:
    doc = pdfium.PdfDocument(str(path))
    try:
        out = []
        for item in doc.get_toc(max_depth=15):
            dest = item.get_dest()
            index = dest.get_index() if dest is not None else None
            out.append({"title": repair(item.get_title()).strip(), "level": item.level + 1, "page": index})
        return out
    finally:
        doc.close()


XMP = re.compile(rb"<x:xmpmeta.*?</x:xmpmeta>", re.S)
XMP_FIELD = {"title": re.compile(r"<dc:title>.*?<rdf:li[^>]*>(.*?)</rdf:li>", re.S),
             "creator": re.compile(r"<dc:creator>(.*?)</dc:creator>", re.S)}
XMP_ITEM = re.compile(r"<rdf:li[^>]*>(.*?)</rdf:li>", re.S)


# the document's XMP packet, which tools write in plain text: its title and creators, entities left as written
def xmp(path: Path) -> dict:
    found = XMP.findall(path.read_bytes())
    if not found:
        return {}
    packet = found[-1].decode("utf-8", errors="replace")
    out = {}
    if m := XMP_FIELD["title"].search(packet):
        out["title"] = repair(html.unescape(m.group(1)).strip())
    if m := XMP_FIELD["creator"].search(packet):
        out["creators"] = [repair(html.unescape(c).strip()) for c in XMP_ITEM.findall(m.group(1)) if c.strip()]
    return {k: v for k, v in out.items() if v}


@_serialised
def info(path: Path) -> dict:
    doc = pdfium.PdfDocument(str(path))
    try:
        return {k: repair(v) for k, v in doc.get_metadata_dict().items() if v}
    finally:
        doc.close()
