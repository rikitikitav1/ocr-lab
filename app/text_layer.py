# the text layer read as the book's text and shapes: joins, lines and their style, faces, drawings, a broken layer
import ctypes
import functools
import re
import statistics
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import alphabets
import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_raw
from pdf import each_page, page_count, pictures, repair

# fewer letters than this is no text layer: a recogniser that lost its alphabet leaves only digits
LAYER_MIN_LETTERS = 40
LAYER_RULE = "letters>=40"

# a monospace face keeps one advance per size across the book, an OCR face one per word, a proportional one per letter
MONO_PAGES = 40
MONO_SPREAD = 0.12
MONO_LETTERS = 50
INVISIBLE = 3


def _advances(page, textpage) -> dict[str, list[float]]:
    out, name = defaultdict(list), ctypes.create_string_buffer(256)
    flags = ctypes.c_int(0)
    for i in range(textpage.count_chars()):
        ch = chr(pdfium_raw.FPDFText_GetUnicode(textpage.raw, i))
        if not ch.isalpha() or unicodedata.east_asian_width(ch) in ("W", "F"):
            continue
        if pdfium_raw.FPDFTextObj_GetTextRenderMode(pdfium_raw.FPDFText_GetTextObject(textpage.raw, i)) == INVISIBLE:
            continue
        matrix = pdfium_raw.FS_MATRIX()
        pdfium_raw.FPDFText_GetMatrix(textpage.raw, i, matrix)
        if matrix.b and abs(matrix.a) < 0.1 * abs(matrix.b):
            continue
        size = pdfium_raw.FPDFText_GetFontSize(textpage.raw, i) * (abs(matrix.d) or 1)
        left, _, right, _ = textpage.get_charbox(i, loose=True)
        if size <= 0 or right <= left:
            continue
        pdfium_raw.FPDFText_GetFontInfo(textpage.raw, i, name, 256, ctypes.byref(flags))
        out[name.value.decode("latin-1", "replace").split("+")[-1]].append((right - left) / size)
    return out


def _spread(advances: list[float]) -> float:
    xs = sorted(advances)
    middle = xs[len(xs) // 2]
    return (xs[int(0.9 * (len(xs) - 1))] - xs[int(0.1 * (len(xs) - 1))]) / middle if middle > 0 else 1.0


# letters set in monospace faces over all letters, on pages sampled across every file of the book
def monospace(paths: list[Path]) -> dict:
    letters, pages, total = defaultdict(list), defaultdict(set), 0
    for k, path in enumerate(paths):
        count = page_count(path)
        picks = sorted({round(i * (count - 1) / (MONO_PAGES - 1)) for i in range(MONO_PAGES)})
        for page, faces in each_page(path, picks, _advances).items():
            for face, advances in faces.items():
                letters[face] += advances
                pages[face].add((k, page))
                total += len(advances)
    faces = [{"face": face, "letters": len(xs), "pages": len(pages[face]), "spread": round(_spread(xs), 3)}
             for face, xs in letters.items() if len(xs) >= MONO_LETTERS and _spread(xs) <= MONO_SPREAD]
    held = set().union(*(pages[f["face"]] for f in faces)) if faces else set()
    return {"share": round(sum(f["letters"] for f in faces) / total, 4) if total else 0.0, "pages": len(held),
            "sampled": MONO_PAGES, "faces": sorted(faces, key=lambda f: -f["letters"])}


@dataclass(frozen=True)
class PageLayer:
    # breaks inside words undone, spaces as PDFium put them: what the referee compares the engines with
    as_read: str
    joined: str
    # the rows the spacing reader joined, as read and as joined
    rows: list


def _rows(text: str, drop: set[int]) -> list[tuple[str, str]]:
    out, start = [], 0
    for end in [i for i, c in enumerate(text) if c in "\r\n"] + [len(text)]:
        if any(start <= k < end for k in drop):
            out.append((text[start:end].strip(), "".join(text[k] for k in range(start, end) if k not in drop).strip()))
        start = end + 1
    return out


def _page_layer(textpage, spaced: bool, solid: Counter | None = None) -> PageLayer:
    text = textpage.get_text_range()
    if len(text) != textpage.count_chars():
        return PageLayer(repair(text), repair(text), [])
    breaks, spaces = _drops(textpage, text, spaced, solid)
    as_read = "".join(c for k, c in enumerate(text) if k not in breaks)
    joined = "".join(c for k, c in enumerate(text) if k not in breaks and k not in spaces)
    return PageLayer(repair(as_read), repair(joined), _rows(text, spaces))


# whether a file's spaced rows are joined, and the words its layer sets solid that check a split by an f
def _joining(path: Path) -> tuple[bool, Counter]:
    spaced = spacing_fits(path)
    return spaced, solid_words(path) if spaced else Counter()


# each page read once: the text as read for the referee, joined for everyone else, and the rows joined
def page_layers(path: Path, pages: list[int] | None = None) -> dict[int, PageLayer]:
    spaced, solid = _joining(path)
    return each_page(path, pages, lambda page, textpage: _page_layer(textpage, spaced, solid))


def page_texts(path: Path, pages: list[int] | None = None) -> dict[int, str]:
    spaced, solid = _joining(path)
    return each_page(path, pages, lambda page, textpage: repair(_joined(textpage, spaced, solid)[0]))


# how often each word stands in a file's layer, lower case: the check a split geometry cannot settle must pass
@functools.lru_cache(maxsize=8)
def solid_words(path: Path) -> Counter:
    texts = each_page(path, None, lambda page, textpage: textpage.get_text_range())
    return Counter(w.lower() for t in texts.values() for w in WORD_RUN.findall(t))


@dataclass(frozen=True)
class Line:
    text: str
    x: float
    top: float
    size: float
    bold: bool
    # set on its side, a quarter turn: a running head printed up the page's edge
    turned: bool = False
    # the first word's own size and weight, since a caption may set only its label apart ("**Figure 1.1** The ...")
    head_size: float = field(default=0.0, compare=False)
    head_bold: bool = field(default=False, compare=False)
    right: float = field(default=0.0, compare=False)


def _low(gaps: list[float]) -> float:
    return sorted(gaps)[len(gaps) * 3 // 10]


def _drops(textpage, text: str, spaced: bool, solid: Counter | None = None) -> tuple[set[int], set[int]]:
    box: list = []
    for i, ch in enumerate(text):
        try:
            box.append(textpage.get_charbox(i) if ch.isalpha() else None)
        except pdfium.PdfiumError:
            box.append(None)
    made = [bool(pdfium_raw.FPDFText_IsGenerated(textpage.raw, i)) for i in range(len(text))]
    return _breaks(text, box, made), (_spaced(textpage, text, made, solid) if spaced else set())


# PDFium breaks lines inside words whose glyphs sit on one row ("Север\r\nе уступае"), and such a break is undone
def _joined(textpage, spaced: bool = False, solid: Counter | None = None) -> tuple[str, list[int]]:
    text = textpage.get_text_range()
    if len(text) != textpage.count_chars():
        return text, list(range(len(text)))
    breaks, spaces = _drops(textpage, text, spaced, solid)
    kept = [k for k in range(len(text)) if k not in breaks and k not in spaces]
    return "".join(text[k] for k in kept), kept


# the file's letter gaps against its word gaps, in em, on advance boxes over pages of its first quarter
SPACING_PAGES = 25


def _gaps(page, textpage) -> tuple[list[float], list[float]]:
    text = textpage.get_text_range()
    if len(text) != textpage.count_chars():
        return [], []
    letters, words = [], []
    for i in range(1, len(text) - 1):
        a, b = (i - 1, i) if text[i].isalpha() and text[i - 1].isalpha() else (i - 1, i + 1)
        if not (text[a].isalpha() and text[b].isalpha()) or (b == i + 1 and text[i] != " "):
            continue
        try:
            left, right = textpage.get_charbox(a, loose=True), textpage.get_charbox(b, loose=True)
        except pdfium.PdfiumError:
            continue
        size = _char_style(textpage, a)[0] or 1.0
        (letters if b == i else words).append((right[0] - left[2]) / size)
    return letters, words


@functools.cache
def spacing_gaps(path: Path) -> tuple[float, float] | None:
    count = page_count(path)
    picks = sorted({round(k * max(count // 4 - 1, 0) / max(SPACING_PAGES - 1, 1)) for k in range(SPACING_PAGES)})
    letters, words = [], []
    for got in each_page(path, picks, _gaps).values():
        letters += got[0]
        words += got[1]
    if len(letters) < 20 or len(words) < 20:
        return None
    letters.sort()
    words.sort()
    return round(letters[int(0.9 * (len(letters) - 1))], 3), round(words[int(0.1 * (len(words) - 1))], 3)


# a layer whose widest letter gaps reach into its narrowest word gaps (an OCR layer's loose boxes) is read as it is
def spacing_fits(path: Path) -> bool:
    gaps = spacing_gaps(path)
    return gaps is not None and gaps[0] < TRACK_WORD * gaps[1]


# a letter-spaced row ("Г Л А В А") is judged whole; its letter gaps sit far under its word gaps
TRACK_EM = 0.25
TRACK_WORD = 0.5
# a split inside a word ("К линическая") sits at the row's own letter gap
SPLIT_SLACK = 0.1
WORD_RUN = re.compile(r"[^\W\d_]+")


def _pair_ok(x: str, y: str) -> bool:
    return (x.isalnum() and y.isalnum()) or (x.isdigit() and y == ".") or (x == "." and y.isdigit())


# a formula's letters stand apart by design; the formula element will mark these rows, a math symbol does it for now
def _mathy(row: str) -> bool:
    return any(unicodedata.category(c) == "Sm" or 0xE000 <= ord(c) <= 0xF8FF for c in row)


def _row_boxes(textpage, text: str, a: int, b: int, loose: bool) -> dict:
    out = {}
    for i in range(a, b):
        if not text[i].isspace():
            try:
                out[i] = textpage.get_charbox(i, loose=loose)
            except pdfium.PdfiumError:
                pass
    return out


def _gap(bx: dict, i: int) -> float | None:
    return bx[i + 1][0] - bx[i - 1][2] if i - 1 in bx and i + 1 in bx else None


def _one_row(bx: dict, i: int, size: float) -> bool:
    p, q = bx[i - 1], bx[i + 1]
    if p[3] > p[1] and q[3] > q[1]:
        return min(p[3], q[3]) - max(p[1], q[1]) >= 0.5 * min(p[3] - p[1], q[3] - q[1])
    return abs(p[1] - q[1]) < 0.3 * size


# the generated spaces PDFium put inside words: letter-spaced rows by the row's gaps, single splits at its letter gap
def _spaced(textpage, text: str, made: list[bool], solid: Counter | None = None) -> set[int]:
    drop: set[int] = set()
    start = 0
    for end in [i for i, c in enumerate(text) if c in "\r\n"] + [len(text)]:
        a, b, start = start, end, end + 1
        spaces = [i for i in range(a + 1, b - 1) if text[i] == " " and not text[i - 1].isspace()
                  and not text[i + 1].isspace()]
        if not any(made[i] for i in spaces) or _mathy(text[a:b]):
            continue
        size = statistics.median(_char_style(textpage, i - 1)[0] for i in spaces) or 1.0
        loose = _row_boxes(textpage, text, a, b, True)
        gaps = {i: g for i in spaces if (g := _gap(loose, i)) is not None and _one_row(loose, i, size)}
        wide = [g for g in gaps.values() if g > TRACK_EM * size]
        tracked = [i for i, g in gaps.items() if made[i] and _pair_ok(text[i - 1], text[i + 1])
                   and 0 <= g <= TRACK_EM * size and (not wide or g < TRACK_WORD * min(wide))]
        tight = [loose[i + 1][0] - loose[i][2] for i in range(a, b - 1) if i in loose and i + 1 in loose]
        letter = statistics.median(tight) if tight else None
        if not (len(tracked) >= 2 and (letter is None or all(gaps[i] <= 2 * letter + 0.3 for i in tracked))):
            tracked = []
        drop.update(tracked)
        ink = _row_boxes(textpage, text, a, b, False)
        inked = [ink[i + 1][0] - ink[i][2] for i in range(a, b - 1) if i in ink and i + 1 in ink]
        if len(inked) < 3:
            continue
        own = statistics.median(inked)
        for i in spaces:
            if i in drop or not made[i] or not (text[i - 1].isalpha() and text[i + 1].isalpha()):
                continue
            g = _gap(ink, i)
            if g is None or not (-1.0 <= g <= own + SPLIT_SLACK and _one_row(ink, i, size)):
                continue
            # an f overhangs its advance, so a word space by it reads as a split: joined if the book sets it solid
            if "f" not in (text[i - 1], text[i + 1]) or _joins(_halves(text, i), solid or Counter()):
                drop.add(i)
    return drop


def _halves(text: str, i: int) -> tuple[str, str]:
    a, b = i, i + 1
    while a > 0 and text[a - 1].isalpha():
        a -= 1
    while b < len(text) and text[b].isalpha():
        b += 1
    return text[a:i].lower(), text[i + 1:b].lower()


# the book sets the joined word solid more often than the rarer half stands alone: "def inition", not "Gulf News"
def _joins(halves: tuple[str, str], solid: Counter) -> bool:
    left, right = halves
    return solid[left + right] > min(solid[left], solid[right])


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


def _char_style(textpage, index: int) -> tuple[float, bool, bool]:
    matrix = pdfium_raw.FS_MATRIX()
    pdfium_raw.FPDFText_GetMatrix(textpage.raw, index, matrix)
    scale = abs(matrix.d) or (matrix.b ** 2 + matrix.d ** 2) ** 0.5 or 1
    size = pdfium_raw.FPDFText_GetFontSize(textpage.raw, index) * scale
    turned = abs(matrix.a) < 0.1 * abs(matrix.b) if matrix.b else False
    return round(size * 2) / 2, pdfium_raw.FPDFText_GetFontWeight(textpage.raw, index) >= 600, turned


# lines as PDFium breaks them less breaks inside a word; position from the first character, style from the most common
def _lines(page, textpage, spaced: bool = False, solid: Counter | None = None) -> list[Line]:
    height = page.get_height()
    text, char_at = _joined(textpage, spaced, solid)
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
        (size, bold, turned), _ = styles.most_common(1)[0]
        word = len(stripped.split()[0])
        head = Counter(_char_style(textpage, char_at[i])[:2] for i in range(first, first + word))
        (head_size, head_bold), _ = head.most_common(1)[0]
        try:
            right = textpage.get_charbox(char_at[begin + len(raw_line.rstrip()) - 1])[2]
        except Exception:
            right = left
        out.append(Line(repair(stripped), round(left, 1), round(height - top, 1), size, bold, turned, head_size,
                        head_bold, round(right, 1)))
    return out


def page_lines(path: Path, pages: list[int] | None = None) -> dict[int, list[Line]]:
    spaced, solid = _joining(path)
    return each_page(path, pages, lambda page, textpage: _lines(page, textpage, spaced, solid))



# a drawn diagram is many vector paths close together; a box's border or a rule is too few to count
DRAWING_MIN_PATHS = 6
# past this many paths a page is read as drawn over its paths' whole extent, not cluster by cluster
DRAWING_MAX_PATHS = 2000


def _drawings(page, textpage) -> list[tuple[float, float, float, float]]:
    w, h = page.get_size()
    paths = []
    for obj in page.get_objects(filter=[pdfium_raw.FPDF_PAGEOBJ_PATH], max_depth=1):
        left, bottom, right, top = obj.get_bounds()
        paths.append((max(left, 0.0), max(h - top, 0.0), min(right, w), min(h - bottom, h)))
    if len(paths) > DRAWING_MAX_PATHS:
        clusters = [(paths, (min(p[0] for p in paths), min(p[1] for p in paths), max(p[2] for p in paths),
                             max(p[3] for p in paths)))]
    else:
        clusters = _clusters(paths, 6.0)
    drawn = [box for members, box in clusters if len(members) >= DRAWING_MIN_PATHS
             and (box[2] - box[0]) * (box[3] - box[1]) >= 0.01 * w * h]
    return pictures(page, textpage) + drawn


# boxes within a gap of each other joined, one pass over a union-find
def _clusters(boxes: list[tuple], gap: float) -> list[tuple[list, tuple]]:
    parent = list(range(len(boxes)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    order = sorted(range(len(boxes)), key=lambda i: boxes[i][0])
    for k, i in enumerate(order):
        for j in order[k + 1:]:
            if boxes[j][0] - gap > boxes[i][2]:
                break
            a, b = boxes[i], boxes[j]
            if a[1] - gap <= b[3] and b[1] - gap <= a[3]:
                parent[root(i)] = root(j)
    groups: dict[int, list] = {}
    for i, box in enumerate(boxes):
        groups.setdefault(root(i), []).append(box)
    return [(g, (min(b[0] for b in g), min(b[1] for b in g), max(b[2] for b in g), max(b[3] for b in g)))
            for g in groups.values()]


# pictures and drawn diagrams in points from the page's top-left, by page index
def page_drawings(path: Path, pages: list[int] | None = None) -> dict[int, list[tuple[float, float, float, float]]]:
    return each_page(path, pages, _drawings)



def letters(text: str) -> int:
    return sum(c.isalpha() for c in text)


def has_layer(text: str) -> bool:
    return letters(text) >= LAYER_MIN_LETTERS


# letters a font with a shifted encoding maps to: phonetic signs and private-use code points; no shelf book had any
SHIFTED_SHARE = 0.3


def _shifted(text: str) -> bool:
    # a private-use glyph is no letter to isalpha, so it is counted beside the letters
    found = [c for c in text if c.isalpha() or ord(c) in alphabets.PRIVATE_USE]
    odd = sum(0x250 <= ord(c) <= 0x2AF or ord(c) in alphabets.PRIVATE_USE for c in found)
    return len(found) >= LAYER_MIN_LETTERS and odd >= SHIFTED_SHARE * len(found)


# almost no letters, or letters in a shifted encoding: a broken layer, recognised again rather than trusted
def garbled(text: str) -> bool:
    printable = sum(c.isprintable() and not c.isspace() for c in text)
    return (printable >= LAYER_MIN_LETTERS and not has_layer(text)) or _shifted(text)


