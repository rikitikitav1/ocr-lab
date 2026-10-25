# one piece from both engines' readings of its pages, put together by the assembly passes; nothing here sees a gold
import hashlib
import json
import re
import time
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

import artifacts
import code_version
import numerals
import pdf
import settings
import text_layer
from assembly import caption_series, passes, referee
from document.model import Code, Figure, Heading, Node, PageMarker, Piece, Table
from engines import converter_tools, reading
from job_signals import Final
from orm.catalogue import Artifact, Book, BookFile, LayoutVersion, StructureNode
from orm.db import Session
from quality import piece as piece_quality
from writers import markdown

from stages import captions as layer_captions
from stages import intake, running_heads
from stages.layout import collect as layout_collect
from stages.layout import page as layout_page
from stages.metadata import resolve
from stages.structure import collect as structure_collect
from stages.structure import evidence, scan, sources

STAGE = "assemble"
ENGINES = settings.ENGINES
READ_CEILING = 1800
# a node longer than this is read as its own pages and its children, never cut by pages
READ_PIECE_PAGES = 100


@dataclass
class Assembled:
    piece: Piece
    markdown: str
    counts: dict = field(default_factory=dict)
    # the blocks after each pass, per file range, for the run's artifacts
    steps: list = field(default_factory=list)
    # the text layer of the piece's pages by book page, for the piece checks
    layer: dict = field(default_factory=dict)
    # running heads and folios each engine set aside, which the layer holds but the piece rightly drops
    furniture: dict = field(default_factory=dict)
    # the figures' pictures by their name in the bundle
    images: dict = field(default_factory=dict)
    # recognised pages by book page, with how far the two engines agree on their words
    recognised: dict = field(default_factory=dict)
    # by book page, the engine each page took, with the referee's scores or the engines' agreement on recognised pages
    pages: dict = field(default_factory=dict)
    # how each page this piece meets a neighbour on was cut
    boundaries: list = field(default_factory=list)
    # the captions the layer sets by the pictures, by book page, for the caption measure
    captions: dict = field(default_factory=dict)
    # per file, its letter and word gaps and whether its letter-spaced rows were joined, as this assembly read them
    spacing: dict = field(default_factory=dict)


# the page layout and structure versions a run started on; a piece assembled outside a run reads the current ones
@dataclass(frozen=True)
class Pinned:
    layout: int | None = None
    structure: int | None = None


CURRENT = Pinned()


def _page_layout(book_id: int, versions: Pinned) -> LayoutVersion | None:
    if versions.layout is None:
        return layout_collect.current(book_id, layout_collect.PAGE)
    with Session() as session:
        return session.get(LayoutVersion, versions.layout)


# the book's languages live with its metadata, where the structure reads them too
languages_in, languages_of = resolve.languages_in, resolve.languages_of


# a number in any language: digits, a Roman numeral of two letters or more, or one set off ("I.", "Part I:", "Глава V")
_ROMAN = numerals.ROMAN_LABEL_UPPER
TITLE_NUMBER = re.compile(rf"^\s*(?:[^\W\d_]+\s+)?(?:\d+(?:\.\d+)*|{_ROMAN})[.:)]?\s+")
NUMBERED = re.compile(rf"\d|\b(?=[IVXLC]{{2}}){_ROMAN}\b|^{_ROMAN}[.:)]|\b{_ROMAN}(?:[.:)]|$)")
EDGE_SHARE = 0.15
# a lone appendix letter ends the title or takes a colon; "Pedro A. de Miguel" is an initial
LONE_LETTER = re.compile(r"\s*(?::|$)")
# a letter as a chapter's number: "Appendix A:", "appendix B", "A Debugging"
LETTERED = re.compile(r"^(?:(?P<word>[^\W\d_]+)\s+)?(?P<letter>[A-Z])(?:[.:)]|\s|$)")


# a node above the level or over a piece's length gives its own pages before its first child, then its children
def pieces_of(rows: list[dict], cut: frozenset[int], level: int, reread: bool = True) -> list[dict]:
    top = min((r["level"] for r in rows), default=0)
    kids = {r["ord"]: [] for r in rows}
    for r in rows:
        if r["parent_ord"] is not None:
            kids[r["parent_ord"]].append(r)
    out = []

    def under(row: dict) -> list[dict]:
        return [k for child in kids[row["ord"]] for k in (child, *under(child))]

    def piece(head: list[dict], first: int, last: int, inner: list[dict]) -> dict:
        nodes = [*head, *inner]
        return {**nodes[0], "first_page": first, "last_page": last, "piece": True,
                "subs": [(r["title"], r["level"]) for r in nodes[1:]], "nodes": nodes}

    # a parent whose first child opens on its first page has no pages of its own: it heads that child's piece
    def walk(row: dict, carried: tuple = ()) -> None:
        span = row["last_page"] - row["first_page"] + 1
        head = [*carried, row]
        if kids[row["ord"]] and (row["level"] - top < level or span > READ_PIECE_PAGES):
            first_child = kids[row["ord"]][0]["first_page"]
            if first_child > row["first_page"]:
                out.append(piece(head, row["first_page"], first_child - 1, []))
                head = []
            for i, child in enumerate(kids[row["ord"]]):
                walk(child, tuple(head) if i == 0 else ())
            return
        out.append(piece(head, row["first_page"], row["last_page"], under(row)))

    for row in rows:
        if row["parent_ord"] is None:
            walk(row)
    out = [c for c in out if not all(p in cut for p in range(c["first_page"], c["last_page"] + 1))]
    # a piece of one page that the next one opens on holds the next one too, or both would keep the page
    merged: list[dict] = []
    for c in out:
        prev = merged[-1] if merged else None
        if prev is not None and prev["first_page"] == prev["last_page"] == c["first_page"]:
            nodes = [*prev["nodes"], *c["nodes"]]
            merged[-1] = {**prev, "last_page": c["last_page"], "nodes": nodes,
                          "subs": [(r["title"], r["level"]) for r in nodes[1:]]}
        else:
            merged.append(c)
    out = merged
    # a piece also reads the next one's first page, so its tail there is cut at the next title, not handed on
    for prev, nxt in zip(out, out[1:], strict=False):
        if reread and nxt["first_page"] == prev["last_page"] + 1 and nxt["first_page"] not in cut:
            prev["last_page"], prev["reread_end"], nxt["reread_start"] = nxt["first_page"], True, True
    return _finished(out, rows)


def _finished(out: list[dict], rows: list[dict]) -> list[dict]:
    pages = max((r["last_page"] for r in rows), default=0)
    # neighbours meeting on a page share it, and each piece is told the other's title to cut it at
    for prev, nxt in zip(out, out[1:], strict=False):
        if nxt["first_page"] == prev["last_page"]:
            prev["next_title"], prev["next_ord"], nxt["shared_start"] = nxt["title"], nxt["ord"], True
    return [{"next_title": None, "next_ord": None, "shared_start": False, **c, "role": role}
            for c, role in zip(out, roles(out, pages), strict=True)]


# the unnumbered pieces before the first numbered one and after the last (a preface, an index) are the book's service
def roles(pieces: list[dict], pages: int) -> list[str]:
    labelled = scan.labels([c["title"] for c in pieces])
    lettered = _lettered([c["title"] for c in pieces])
    numbered = [i for i, c in enumerate(pieces) if NUMBERED.search(c["title"]) or i in lettered
                or (m := scan.STYLE_LABELLED.match(c["title"].strip())) and m.group(1).lower() in labelled]
    # numbering that starts deep in the book means its pieces are unnumbered, not that they are a preface
    if not numbered or pieces[numbered[0]]["first_page"] > EDGE_SHARE * pages:
        return ["body"] * len(pieces)
    first, last = numbered[0], numbered[-1]
    # numbering that ends early leaves unnumbered pieces after it, not back matter
    if pages - pieces[last]["last_page"] > EDGE_SHARE * pages:
        last = len(pieces) - 1
    return ["service" if i < first or i > last else "body" for i in range(len(pieces))]


# consecutive letters in a row after the same word or none, or a lone "Appendix A": a bare "A" alone is an article
def _lettered(titles: list[str]) -> set[int]:
    hits = [(i, m) for i, t in enumerate(titles) if (m := LETTERED.match(t.strip()))]
    out = {i for i, m in hits
           if m["word"] and m["letter"] == "A" and LONE_LETTER.match(titles[i].strip()[m.end("letter"):])}
    for (i, m), (j, n) in zip(hits, hits[1:], strict=False):
        same_word = (m["word"] or "").lower() == (n["word"] or "").lower()
        if j == i + 1 and ord(n["letter"]) == ord(m["letter"]) + 1 and same_word:
            out |= {i, j}
    return out


# a piece's book pages split at file boundaries and around cut pages, as (file, first and last page in that file)
def file_ranges(files: list[BookFile], first: int, last: int,
                cut: frozenset[int] = frozenset()) -> list[tuple[BookFile, int, int]]:
    out = []
    for f in files:
        a, b = max(first, f.first_page), min(last, f.first_page + f.pages - 1)
        start = None
        for page in range(a, b + 2):
            if page <= b and page not in cut:
                start = page if start is None else start
            elif start is not None:
                out.append((f, start - f.first_page + 1, page - f.first_page))
                start = None
    return out


# the printed contents pages the structure version found; the bundle leaves them out, they repeat the structure
def _contents_pages(structure_version_id: int) -> frozenset[int]:
    with Session() as session:
        found = (evidence.read(session, structure_version_id) or {}).get("printed_contents") or {}
    return frozenset((found.get("notes") or {}).get("pages") or [])


# the book's first page before the first real structure node is a cover or a title page, which metadata reads instead
def _cover(rows: list[dict]) -> frozenset[int]:
    first = next((r["first_page"] for r in rows if r["kind"] != "front_matter"), 1)
    return frozenset({1}) if first > 1 else frozenset()


# the pages the bundle leaves out, by why: printed contents and the cover
def cut_pages(structure_version_id: int, rows: list[dict]) -> dict[str, frozenset[int]]:
    return cut_of(rows, _contents_pages(structure_version_id))


def cut_of(rows: list[dict], contents: frozenset[int]) -> dict[str, frozenset[int]]:
    return {"contents": contents, "cover": _cover(rows)}


# pages read by recognition: every page of a scanned book, else the pages the intake probe found without a usable layer
def scanned_pages(book_id: int) -> frozenset[int]:
    with Session() as session:
        book = session.get(Book, book_id)
        if scan.is_scan(book):
            return frozenset(range(1, (book.pages or 0) + 1))
        layer = book.text_layer or {}
        return frozenset(layer.get("without_layer", [])) | frozenset(layer.get("garbled", []))


# a piece's file ranges split again where the regime changes, as (file, first, last, regime)
def ranges(book_id: int, first: int, last: int, cut: frozenset[int] = frozenset()) -> list[tuple]:
    scanned, out = scanned_pages(book_id), []
    for f, a, b in file_ranges(intake.files_of(book_id), first, last, cut):
        start = a
        for page in range(a, b + 1):
            regime = "scan" if f.first_page + page - 1 in scanned else "text_pdf"
            nxt = "scan" if f.first_page + page in scanned else "text_pdf"
            if page == b or nxt != regime:
                out.append((f, start, page, regime))
                start = page + 1
    return out


# a name of its own, so door tests stand a build in for the piece readings only
_build = reading.build


# a reading is kept per file range, fields and engine build, so a rerun of the piece reads nothing again
def _reading_key(f: BookFile, a: int, b: int, engine: str, languages: list[str], regime: str):
    given = reading.fields(engine, regime, languages)
    build = _build(engine)
    made_from = artifacts.Inputs({"stage": STAGE, "file": f.sha256, "pages": [a, b], "fields": given,
                                  "build": build})
    name = f"reading.{engine}.{f.ord}.{a}-{b}{'' if regime == 'text_pdf' else '.' + regime}.json"
    return artifacts.Owner(book_id=f.book_id), name, made_from, given, build


# every range of the pages is read already, so reading them again costs a lookup, not an engine call
def readings_kept(book_id: int, engine: str, first_page: int, last_page: int, languages: list[str] | None = None,
                  cut: frozenset[int] = frozenset()) -> bool:
    languages = languages or languages_of(book_id)
    for f, a, b, regime in ranges(book_id, first_page, last_page, cut):
        owner, name, made_from, _, _ = _reading_key(f, a, b, engine, languages, regime)
        if artifacts.find_done(owner, STAGE, name, made_from.key) is None:
            return False
    return True


def _reading(book_id: int, f: BookFile, a: int, b: int, engine: str, languages: list[str],
             regime: str = "text_pdf") -> Artifact:
    owner, name, made_from, given, build = _reading_key(f, a, b, engine, languages, regime)
    done = artifacts.find_done(owner, STAGE, name, made_from.key)
    if done is not None:
        return done
    started = time.perf_counter()
    structure = reading.read(engine, settings.DATA_DIR / f.file_path, a, b, given, READ_CEILING, build)
    # the reading's own cost, so a run that takes it from the cache still reports what the book took to read
    return artifacts.write(owner, artifacts.book_dir(book_id), STAGE, name, structure, made_from, heavy=True,
                           keyed=True, meta={"engine": engine, "seconds": round(time.perf_counter() - started, 2)})


def _structure(book_id: int, f: BookFile, a: int, b: int, engine: str, languages: list[str],
               regime: str = "text_pdf") -> dict:
    return converter_tools.kept_json(_reading(book_id, f, a, b, engine, languages, regime))


# the key a piece's read jobs name their readings by, so the assembly takes exactly what was read
def reading_key(engine: str, f: BookFile, a: int, b: int, regime: str) -> str:
    return f"{engine}:{f.ord}:{a}-{b}:{regime}"


# the pages a piece's read jobs read: a page it takes only for its tail is read by the next piece
def read_pages(entry: dict) -> tuple[int, int]:
    return entry["first_page"], entry["last_page"] - int(bool(entry.get("reread_end")))


# one engine over a piece's file ranges, each reading kept; the run reads engine by engine so the card moves twice
def read(book_id: int, engine: str, first_page: int, last_page: int, languages: list[str] | None = None,
         cut: frozenset[int] = frozenset()) -> dict[str, int]:
    languages = languages or languages_of(book_id)
    return {reading_key(engine, f, a, b, regime): _reading(book_id, f, a, b, engine, languages, regime).id
            for f, a, b, regime in ranges(book_id, first_page, last_page, cut)}


# the page layout read from (the run's, else the current) and what it holds; a scan's skipped layout holds nothing
def _layout(book_id: int, versions: Pinned) -> tuple[LayoutVersion | None, dict]:
    kept = _page_layout(book_id, versions)
    return kept, kept.layout if kept is not None and "skipped" not in kept.layout else {}


# the modules each book-level list is made by: a list keyed by a file its make no longer reads is served stale
LIST_CODE = {"running_heads.json": (running_heads, layout_page), "slot_lines.json": (layout_page,),
             "note_lines.json": (layout_page,), "captions.json": (layer_captions, caption_series, sources),
             "series_captions.json": (caption_series, sources)}


# set by a gate: the book-level lists are made anew, not read back, and each one's hash is kept here by name
FRESH: ContextVar[dict | None] = ContextVar("fresh_lists", default=None)


# a book-level list by page kept under its inputs: made once, read back with its page keys as numbers again
def _by_page(book_id: int, name: str, parts: dict, make: Callable, row: Callable = lambda v: v) -> dict:
    files = intake.files_of(book_id)
    code = [Path(m.__file__) for m in LIST_CODE[name]]
    made_from = artifacts.Inputs({"stage": STAGE, "files": [f.sha256 for f in files], **parts,
                                  "code": code_version.files_hash(code).hexdigest()[:16]})
    if (fresh := FRESH.get()) is not None:
        if (name, made_from.key) not in fresh:
            made = make(files)
            fresh[(name, made_from.key)] = json.dumps(made, ensure_ascii=False)
            fresh[name] = hashlib.sha256(json.dumps(made, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]
        return {int(k): row(v) for k, v in json.loads(fresh[(name, made_from.key)]).items()}
    owner = artifacts.Owner(book_id=book_id)
    done = artifacts.find_done(owner, STAGE, name, made_from.key)
    if done is not None:
        return {int(k): row(v) for k, v in json.loads(artifacts.read(done)).items()}
    out = make(files)
    artifacts.write(owner, artifacts.book_dir(book_id), STAGE, name, out, made_from, keyed=True)
    return out


# the book's running heads by page: lines repeated at a page's edge, and the slot lines its page layout claims by reason
def running(book_id: int, versions: Pinned = CURRENT) -> dict[int, list[str]]:
    kept, layout = _layout(book_id, versions)

    def make(files) -> dict:
        lines = sources.book_lines(files)
        heads = running_heads.layer_heads(lines)
        page_of = {id(x): p for p, ls in lines.items() for x in ls}
        for key, (line, _) in layout_page.claimed_reasons(lines, layout).items() if layout else ():
            on_page = heads.setdefault(page_of[key], [])
            if line.text not in on_page:
                on_page.append(line.text)
        return heads

    return _by_page(book_id, "running_heads.json", {"layout": kept.id if kept is not None else None}, make)


# the slot lines the page layout claims by reason (folio, repeat, side), by book page, for the slot reader
def slot_lines(book_id: int, versions: Pinned = CURRENT) -> dict[int, list[tuple[str, str, float]]]:
    kept, layout = _layout(book_id, versions)
    if not layout:
        return {}

    def make(files) -> dict:
        lines = sources.book_lines(files)
        page_of = {id(x): p for p, ls in lines.items() for x in ls}
        heights = {f.first_page + i: h for f in files
                   for i, (_, h) in enumerate(pdf.page_sizes(settings.DATA_DIR / f.file_path))}
        out: dict[int, list[tuple[str, str, float]]] = {}
        for key, (line, reason) in layout_page.claimed_reasons(lines, layout).items():
            page = page_of[key]
            out.setdefault(page, []).append((line.text, reason, round(line.top / heights[page], 4)))
        return out

    return _by_page(book_id, "slot_lines.json", {"layout": kept.id, "with": "top"}, make,
                    lambda v: [tuple(x) for x in v])


# the lines the page layout reads as notes, per book page, joined and spaced for a word-bounded search
def note_lines(book_id: int, versions: Pinned = CURRENT) -> dict[int, str]:
    kept, layout = _layout(book_id, versions)
    if not layout.get("notes"):
        return {}

    def make(files) -> dict:
        lines = sources.book_lines(files)
        notes = layout_page.claimed(lines, layout) - layout_page.claimed(lines, {**layout, "notes": None})
        return {p: " " + " ".join(" ".join(x.text for x in ls if id(x) in notes).split()).casefold() + " "
                for p, ls in lines.items() if any(id(x) in notes for x in ls)}

    return _by_page(book_id, "note_lines.json", {"layout": kept.id}, make)


# the book's picture captions by page, read from the PDF's pictures and the layer's lines beside them
def captions(book_id: int) -> dict[int, list[str]]:
    def make(files) -> dict:
        found = {}
        # the body size is a file's own: a book bound from several files may set them in different sizes
        for f in files:
            pictures = {f.first_page + i: b for i, b in pdf.page_pictures(settings.DATA_DIR / f.file_path).items() if b}
            if pictures:
                found |= layer_captions.by_page(pictures, sources.book_lines([f], set(pictures)))
        return found

    return _by_page(book_id, "captions.json", {}, make)


# the book's captions in its own numbered series, by book page, read from the layer's lines alone
def series_captions(book_id: int, versions: Pinned = CURRENT) -> dict[int, list[str]]:
    version = versions.structure
    if version is None and (current := structure_collect.current_version(book_id)) is not None:
        version = current.id
    with Session() as session:
        titles = frozenset(n.title for n in session.query(StructureNode).filter_by(
            structure_version_id=version)) if version is not None else frozenset()

    def make(files) -> dict:
        def drawings(page: int) -> list:
            f = intake.file_of(files, page)
            if f is None:
                return []
            index = page - f.first_page
            return text_layer.page_drawings(settings.DATA_DIR / f.file_path, [index]).get(index, [])

        return caption_series.learn(sources.book_lines(files), titles, cache(drawings))

    return _by_page(book_id, "series_captions.json", {"structure": version}, make)


def builds() -> dict:
    return {engine: _build(engine) for engine in ENGINES}


# a figure's picture is cut from the page by its box, so it does not depend on what an engine exports
def _kept_figures(path, blocks: list, keep: Callable[[bytes], str]) -> list:
    out = []
    for block in blocks:
        if isinstance(block, Figure) and block.where is not None and not markdown.image_kept(block.image):
            block = block.model_copy(update={"image": keep(pdf.page_crop(path, block.where.page - 1,
                                                                          block.where.box))})
        out.append(block)
    return out


# the readings the piece's read jobs named, or, without them (an evaluation), the ones kept for today's key
def _kept(book_id: int, f: BookFile, a: int, b: int, regime: str, engine: str, languages: list[str],
          readings: dict[str, int] | None) -> dict:
    if readings is None:
        return _structure(book_id, f, a, b, engine, languages, regime)
    key = reading_key(engine, f, a, b, regime)
    with Session() as session:
        row = session.get(Artifact, readings[key]) if key in readings else None
    if row is None:
        raise Final(f"no {engine} reading of file {f.ord} pages {a}-{b} ({regime}) among this round's reads")
    # a kept reading passes the text cleaning of today's code, as the structure and metadata stages read theirs
    return converter_tools.kept_json(row)


def _segment(blocks: list, page: int) -> tuple[int, int] | None:
    marks = [i for i, b in enumerate(blocks) if isinstance(b, PageMarker)]
    return next(((i, j) for i, j in zip(marks, [*marks[1:], len(blocks)], strict=True)
                 if blocks[i].book_page == page), None)


# the next piece's reading of a boundary page stands in for this piece's own, so both cut one reading
def _neighbours_page(book_id: int, f: BookFile, page: int, regime: str, engine: str, languages: list[str],
                     neighbour: dict[str, int]) -> list | None:
    head = f"{engine}:{f.ord}:{page - f.first_page + 1}-"
    key = next((k for k in neighbour if k.startswith(head) and k.endswith(f":{regime}")), None)
    if key is None:
        return None
    a, b = map(int, key.split(":")[2].split("-"))
    blocks = reading.adapt(engine, _kept(book_id, f, a, b, regime, engine, languages, neighbour), file_ord=f.ord,
                           book_page=lambda p, f=f: f.first_page + p - 1).blocks
    span = _segment(blocks, page)
    return blocks[span[0]:span[1]] if span else None


# a run read before its pieces left the tail page to the next one holds a reading of the whole range
def _read_whole(readings: dict[str, int] | None, f: BookFile, a: int, b: int, regime: str) -> bool:
    return readings is not None and all(reading_key(e, f, a, b, regime) in readings for e in ENGINES)


# the tail page as the next piece read it, alone: the piece's own range ended on it
def _borrowed(book_id: int, f: BookFile, page: int, regime: str, engine: str, languages: list[str],
              neighbour: dict[str, int]):
    head = f"{engine}:{f.ord}:{page - f.first_page + 1}-"
    key = next((k for k in neighbour if k.startswith(head) and k.endswith(f":{regime}")), None)
    if key is None:
        return None
    a, b = map(int, key.split(":")[2].split("-"))
    got = reading.adapt(engine, _kept(book_id, f, a, b, regime, engine, languages, neighbour), file_ord=f.ord,
                        book_page=lambda p: f.first_page + p - 1)
    span = _segment(got.blocks, page)
    got.blocks, got.furniture = (got.blocks[span[0]:span[1]] if span else []), []
    return got


def _range_blocks(book_id: int, f: BookFile, a: int, b: int, regime: str, languages: list[str], got: Assembled,
                  counts: dict, keep: Callable[[bytes], str], knobs: dict,
                  readings: dict[str, int] | None = None, boundaries: list[passes.Boundary] = (),
                  neighbour: dict[str, int] | None = None, tail_page: int | None = None,
                  versions: Pinned = CURRENT) -> list:
    path = settings.DATA_DIR / f.file_path
    lent = tail_page == f.first_page + b - 1 and neighbour is not None and not _read_whole(readings, f, a, b, regime)
    own = b - 1 if lent else b
    if own < a:
        reads = {e: _borrowed(book_id, f, tail_page, regime, e, languages, neighbour) for e in ENGINES}
        if any(r is None for r in reads.values()):
            counts["tail_page_unread"] = counts.get("tail_page_unread", 0) + 1
            return []
    else:
        reads = {e: reading.adapt(e, _kept(book_id, f, a, own, regime, e, languages, readings), file_ord=f.ord,
                                  book_page=lambda page, f=f: f.first_page + page - 1) for e in ENGINES}
    # the tail page comes whole from the next piece's reading of it; one it lacks is counted, not read here
    for e, r in reads.items() if lent and own >= a else ():
        theirs = _neighbours_page(book_id, f, tail_page, regime, e, languages, neighbour)
        if theirs is None:
            counts["tail_page_unread"] = counts.get("tail_page_unread", 0) + 1
        else:
            r.blocks += theirs
    here = [x for x in boundaries if f.first_page + a - 1 <= x.page <= f.first_page + b - 1]
    for x in here:
        for e, r in reads.items():
            theirs = _neighbours_page(book_id, f, x.page, regime, e, languages, neighbour) \
                if x.tail and neighbour else None
            span = _segment(r.blocks, x.page)
            if theirs is not None and span is not None:
                r.blocks = r.blocks[:span[0]] + theirs + r.blocks[span[1]:]
            elif x.tail and span is not None:
                # without the next piece's reading the tail is cut from this piece's own re-read, and counted
                counts["boundary_own_reading"] = counts.get("boundary_own_reading", 0) + 1
    ranged: list = []
    if regime == "scan":
        scan_engine = knobs["scan_engine"]
        blocks, found, agreement = passes.recognised(reads, scan_engine, ranged,
                                                     piece_quality.conf()["layer_min_words"], here,
                                                     got.boundaries)
        got.recognised.update({f.first_page + page - 1: share for page, share in agreement.items()})
        got.pages.update({f.first_page + page - 1: {"picked": scan_engine, "agreement": share}
                          for page, share in agreement.items()})
    else:
        # the referee compares the engines with the layer as read, so the joined rows cannot move its picks
        read = text_layer.page_layers(path, list(range(a - 1, b)))
        layer = {i + 1: r.as_read for i, r in read.items()}
        got.layer.update({f.first_page + i: r.joined for i, r in read.items()})
        glyphs = cache(lambda page: pdf.page_glyphs(path, page - 1))
        picks: dict = {}
        gaps = text_layer.spacing_gaps(path)
        got.spacing[f.ord] = {"letters_p90": gaps[0] if gaps else None, "words_p10": gaps[1] if gaps else None,
                              "joined": text_layer.spacing_fits(path)}
        claimed = slot_lines(book_id, versions)
        slots = {p - f.first_page + 1: claimed[p] for p in range(f.first_page + a - 1, f.first_page + b)
                 if p in claimed}
        joined = {i + 1: r.rows for i, r in read.items() if r.rows}
        noted = note_lines(book_id, versions) if knobs.get("notes_from_furniture") else {}
        notes = {p - f.first_page + 1: noted[p] for p in range(f.first_page + a - 1, f.first_page + b) if p in noted}
        captions = series_captions(book_id, versions) if knobs.get("caption_series") else {}
        blocks, found = passes.apply(reads, layer, glyphs, ENGINES, ranged, knobs, picks, here, got.boundaries,
                                     slots=slots, joined_rows=joined, notes=notes, captions=captions)
        got.pages.update({f.first_page + page - 1: picked for page, picked in picks.items()})
    got.steps.append({"file": f.ord, "pages": [a, b], "regime": regime, "steps": ranged})
    for key, n in found.items():
        counts[key] = counts.get(key, 0) + n
    # running heads and folios each engine set aside, counted for the piece's report
    for engine, r in reads.items():
        counts[f"furniture_{engine}"] = counts.get(f"furniture_{engine}", 0) + len(r.furniture)
        got.furniture.setdefault(engine, []).extend(r.furniture)
    return _kept_figures(path, blocks, keep)


def _node(row: dict) -> dict:
    return {k: row.get(k) for k in ("ord", "title", "level", "parent_ord", "first_page", "last_page")}


# a label heading set right above a node's title ("ГЛАВА 2" over its name) opens the node, not the one before
def _label_above(blocks: list, at: int, pinned: list[int | None]) -> int:
    above = next((i for i in range(at - 1, -1, -1) if not isinstance(blocks[i], PageMarker)), None)
    if above is not None and above not in pinned and isinstance(blocks[above], Heading) \
            and numerals.LABEL_LINE.match(blocks[above].text):
        return above
    return at


# a node no heading was pinned to opens at a short block reading as its title on its first page, else at that page's top
def _placed(blocks: list, row: dict, level: int, taken: set[int],
            after_on_page: bool) -> tuple[int, Heading, str] | None:
    marks = [i for i, b in enumerate(blocks) if isinstance(b, PageMarker) and b.book_page == row["first_page"]]
    if not marks or level < 1:
        return None
    start = marks[0] + 1
    end = next((i for i in range(start, len(blocks)) if isinstance(blocks[i], PageMarker)), len(blocks))
    # code and tables are the book's content, never a title, even when a line of them reads as one
    def prose(i: int | None) -> int | None:
        return None if i is None or isinstance(blocks[i], (Code, Table)) else i

    at, how = prose(passes.titled(blocks, start, end, row["title"])), "placed_title"
    # a title printed with its number apart ("16" over "Adapter" for "16. Adapter") is sought without it
    core = TITLE_NUMBER.sub("", row["title"], count=1).strip()
    if at is None and core and core != row["title"].strip():
        at, how = prose(passes.titled(blocks, start, end, core)), "placed_number"
    if at is None:
        at, how = prose(passes.titled_loosely(blocks, start, end, row["title"])), "placed_loose"

    # a block another node already opens at stays that node's: this one is set at the page's top instead
    if at is not None and at not in taken and not (isinstance(blocks[at], Heading) and blocks[at].node is not None):
        return at, Heading(text=referee.block_text(blocks[at]), level=level, level_source="structure", node=row["ord"],
                           where=blocks[at].where), how
    # on a page the node before it opens on too, its place is unknown: its text stays in that node
    if after_on_page:
        return None
    return -start, Heading(text=row["title"], level=level, level_source="page", node=row["ord"]), "placed_top"


# each inner node marks the heading pinned to it; a node whose heading is not found keeps its text in the one before
def _opened(blocks: list, pinned: list[int | None], nodes: list[dict], node_level: int = 1,
            piece: bool = False, own_first: int | None = None, fired: dict | None = None) -> tuple[list, list[Node]]:
    out, found, placed = list(blocks), [], []
    fired = {} if fired is None else fired
    ceiling = passes.MAX_LEVEL - (node_level + 1)
    for at, row in zip(pinned, nodes, strict=True):
        if piece and at is not None and isinstance(out[at], Heading):
            label = _label_above(out, at, pinned)
            if label != at:
                out[label] = out[label].model_copy(update={"level": out[at].level})
                at = label
                fired["label_opened"] = fired.get("label_opened", 0) + 1
        opens = at is not None and isinstance(out[at], Heading)
        if opens:
            out[at] = out[at].model_copy(update={"node": row["ord"]})
        elif piece and at is None and (spot := _placed(out, row, min(max(1, row["level"] - node_level), ceiling, 5),
                                                       {i for i in pinned if i is not None} | {s for s, _ in placed},
                                                       bool(found) and found[-1].first_page == row["first_page"]
                                                       or not found and own_first == row["first_page"])):
            placed.append(spot[:2])
            fired[spot[2]] = fired.get(spot[2], 0) + 1
            opens = True
        found.append(Node(**_node(row), pinned=at is not None, anchored=opens))
    # a negative spot inserts before that block, a positive one turns it into the heading; from the end, in node order
    order = sorted(range(len(placed)), key=lambda i: (abs(placed[i][0]), placed[i][0] > 0, i), reverse=True)
    for spot, heading in (placed[i] for i in order):
        if spot < 0:
            out.insert(-spot, heading)
        else:
            out[spot] = heading
    return out, found


# every block goes to the node whose anchor last opened before it, the piece's own node before any
def _owned(blocks: list, own: int, first_by_page: bool) -> list:
    out, owner, anchor_by_page, page = [], own, False, 0
    for b in blocks:
        if isinstance(b, PageMarker):
            page += 1
            out.append(b)
            continue
        if isinstance(b, Heading) and b.node is not None:
            owner, anchor_by_page = b.node, b.level_source == "page"
        by_page = anchor_by_page if owner != own else first_by_page and page <= 1
        out.append(b.model_copy(update={"parent_ord": owner, "by_page": by_page}))
    return out


# the counters the shared-page cut kept, read off the boundary records
def _boundary_counts(records: list[dict]) -> dict:
    read = [r for r in records if r["read"]]
    return {"shared_cut_start": int(any(r["title_found"] for r in read if not r["tail"])),
            "shared_cut_end": int(any(r["title_found"] for r in read if r["tail"])),
            "shared_title_missing": sum(not r["title_found"] for r in read),
            "shared_cut_blocks": sum(r["dropped"] for r in read)}


# the node's own heading is written by the writer, so the structure level is the node's place in the book
def assemble(book_id: int, ord: int, title: str, level: int, first_page: int, last_page: int,
             subs: list[tuple[str, int]] = (), languages: list[str] | None = None,
             cut: frozenset[int] = frozenset(), role: str = "body", knobs: dict | None = None,
             readings: dict[str, int] | None = None, shared_start: bool = False,
             next_title: str | None = None, nodes: list[dict] = (), piece: bool = False,
             reread_end: bool = False, boundaries: list[passes.Boundary] | None = None,
             neighbour: dict[str, int] | None = None, versions: Pinned = CURRENT) -> Assembled:
    got = Assembled(None, "")
    counts = got.counts

    def keep(png: bytes) -> str:
        name = f"images/{ord:02d}-{len(got.images) + 1:03d}.png"
        got.images[name] = png
        return name

    languages = languages or languages_of(book_id)
    # the profile's knobs over the passes' defaults, read once for the whole piece
    knobs = {**passes.conf(), **(knobs or {})}
    blocks = []
    for f, a, b, regime in ranges(book_id, first_page, last_page, cut):
        blocks += _range_blocks(book_id, f, a, b, regime, languages, got, counts, keep, knobs, readings,
                                boundaries or (), neighbour, last_page if reread_end else None, versions)
    counts["pages_cut"] = sum(first_page <= p <= last_page for p in cut)
    heads = running(book_id, versions)
    got.furniture["layer"] = [text for page in got.layer for text in heads.get(page, [])]
    got.captions = {p: c for p, c in captions(book_id).items() if first_page <= p <= last_page}
    node_level = min(max(level, 1), 5)
    # the piece passes after the range passes, each snapshot taken as it stood, since later passes edit blocks in place
    piece_steps: list = []
    got.steps.append({"file": "piece", "pages": [first_page, last_page], "regime": None, "steps": piece_steps})

    def step(name: str) -> None:
        piece_steps.append((name, [b.model_copy(deep=True) for b in blocks]))

    if boundaries is None:
        blocks, shared = passes.shared_pages(blocks, title, shared_start, next_title,
                                             last_page if reread_end else None)
    else:
        shared = _boundary_counts(got.boundaries)
    counts.update(shared)
    step("shared_pages")
    title_found = passes.title_on_first_page(blocks, title)
    blocks, counts["title_dropped"] = passes.without_title(blocks, title)
    step("without_title")
    # a chapter's own section list is set apart before the pins, so no node is pinned to its line in it
    if nodes and knobs.get("chapter_contents"):
        blocks, counts["chapter_contents"] = passes.chapter_contents(blocks, list(nodes), got.layer)
    step("chapter_contents")
    own_pages = [(r["first_page"], r["last_page"]) for r in list(nodes)[1:]] if nodes else None
    pinned = passes.pins(blocks, [t for t, _ in subs], counts, own_pages)
    blocks, levelled = passes.piece_levels(blocks, node_level, list(subs), pinned)
    counts.update(levelled)
    step("piece_levels")
    fired = {k: 0 for k in ("label_opened", "placed_title", "placed_number", "placed_loose", "placed_top")}
    blocks, inner = (_opened(blocks, pinned, list(nodes)[1:], node_level, piece, nodes[0]["first_page"], fired)
                     if nodes else (blocks, []))
    counts.update(fired)
    step("opened")
    if knobs.get("caption_series"):
        blocks, counts["series_captions"] = passes.series_captions(blocks, series_captions(book_id, versions))
    step("series_captions")
    blocks, counts["slot_dropped"] = passes.drop_slots(blocks)
    step("slots_dropped")
    counts["reread_cut"] = int(reread_end and bool(counts.get("shared_cut_end")))
    blocks = _owned(blocks, nodes[0]["ord"] if nodes else ord, shared_start and not counts["shared_cut_start"])
    step("owned")
    counts["blocks"] = sum(not isinstance(b, PageMarker) for b in blocks)
    counts["blocks_by_page"] = sum(getattr(b, "by_page", False) for b in blocks)
    own = [Node(**_node(n), pinned=title_found, anchored=True) for n in list(nodes)[:1]]
    got.piece = Piece(ord=ord, title=title, level=node_level, first_page=first_page, last_page=last_page,
                          role=role, blocks=blocks, nodes=own + inner)
    got.markdown = markdown.piece(got.piece)
    return got
