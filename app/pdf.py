# thin helpers over pypdfium2: pages, glyphs, crops, pictures, outline and file info; text_layer.py reads the text
import functools
import html
import re
import struct
import threading
import zlib
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

# a picture smaller than this share of the page is an icon or a rule, not a figure
PICTURE_MIN_AREA = 0.02


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
# a glyph's box, its character, and whether the text puts a space before it on its line
def page_glyphs(path: Path, page_index: int) -> list[tuple[float, float, float, float, str, bool]]:
    doc = pdfium.PdfDocument(str(path))
    try:
        page = doc[page_index]
        width, height = page.get_size()
        textpage = _text_page(page)
        out, spaced = [], False
        for i in range(textpage.count_chars()):
            ch = textpage.get_text_range(i, 1)
            if not ch or ch in ("\r", "\n") or ch.isspace():
                spaced = bool(ch) and ch not in ("\r", "\n")
                continue
            left, bottom, right, top = textpage.get_charbox(i, loose=True)
            out.append((left / width, 1 - top / height, right / width, 1 - bottom / height,
                        "-" if ch == "\ufffe" else repair(ch), spaced))
            spaced = False
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


# PDFium loads glyphs on a first render and char boxes differ after it, so every page is rendered small before reading
GLYPH_SCALE = 0.05


def _text_page(page):
    page.render(scale=GLYPH_SCALE, draw_annots=False)
    return page.get_textpage()


# one reading per page, the file opened once and every page closed after its reading
@_serialised
def each_page(path: Path, pages: list[int] | None, read) -> dict:
    doc = pdfium.PdfDocument(str(path))
    try:
        wanted = range(len(doc)) if pages is None else [p for p in pages if 0 <= p < len(doc)]
        out = {}
        for i in wanted:
            page = doc[i]
            textpage = _text_page(page)
            out[i] = read(page, textpage)
            textpage.close()
            page.close()
        return out
    finally:
        doc.close()


# one picture is often cut into tiles: boxes that touch or nearly touch are one region
def _merged(boxes: list[tuple], sx: float, sy: float) -> list[tuple]:
    out = list(boxes)
    joined = True
    while joined:
        joined = False
        for a in range(len(out)):
            for b in range(a + 1, len(out)):
                p, q = out[a], out[b]
                if p[0] - sx <= q[2] and q[0] - sx <= p[2] and p[1] - sy <= q[3] and q[1] - sy <= p[3]:
                    out[a] = (min(p[0], q[0]), min(p[1], q[1]), max(p[2], q[2]), max(p[3], q[3]))
                    del out[b]
                    joined = True
                    break
            if joined:
                break
    return out


# an image inside a form XObject reports the form's coordinates, so only top-level image and form objects are read
def pictures(page, textpage) -> list[tuple[float, float, float, float]]:
    w, h = page.get_size()
    boxes = []
    for obj in page.get_objects(filter=[pdfium_raw.FPDF_PAGEOBJ_IMAGE, pdfium_raw.FPDF_PAGEOBJ_FORM], max_depth=0):
        left, bottom, right, top = obj.get_bounds()
        boxes.append((max(left, 0.0), max(h - top, 0.0), min(right, w), min(h - bottom, h)))
    return [b for b in _merged(boxes, 0.01 * w, 0.01 * h) if b[0] < b[2] and b[1] < b[3]
            and (b[2] - b[0]) * (b[3] - b[1]) >= PICTURE_MIN_AREA * w * h and b[2] - b[0] < 0.98 * w]


# picture regions in points from the page's top-left, by page index
def page_pictures(path: Path, pages: list[int] | None = None) -> dict[int, list[tuple[float, float, float, float]]]:
    return each_page(path, pages, pictures)


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
