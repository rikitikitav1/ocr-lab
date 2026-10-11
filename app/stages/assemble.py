# one chapter from both engines' readings of its pages, put together by the assembly passes; nothing here sees a gold
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

import artifacts
import code_version
import numerals
import pdf
import settings
from assembly import passes
from document.model import Chapter, Figure
from engines import converter_tools, reading
from job_signals import Final
from orm.catalogue import Artifact, Book, BookFile, MetadataField
from orm.db import Session
from quality import chapter as chapter_quality
from sqlalchemy import select
from writers import markdown

from stages import intake, running_heads
from stages.metadata import resolve
from stages.toc import evidence, scan, sources

STAGE = "assemble"
ENGINES = settings.ENGINES
READ_CEILING = 1800


@dataclass
class Assembled:
    chapter: Chapter
    markdown: str
    counts: dict = field(default_factory=dict)
    # the blocks after each pass, per file range, for the run's artifacts
    steps: list = field(default_factory=list)
    # the text layer of the chapter's pages by book page, for the chapter checks
    layer: dict = field(default_factory=dict)
    # running heads and folios each engine set aside, which the layer holds but the chapter rightly drops
    furniture: dict = field(default_factory=dict)
    # the figures' pictures by their name in the bundle
    images: dict = field(default_factory=dict)
    # recognised pages by book page, with how far the two engines agree on their words
    recognised: dict = field(default_factory=dict)
    # by book page, the engine each page took, with the referee's scores or the engines' agreement on recognised pages
    pages: dict = field(default_factory=dict)


# the languages of one metadata version, set by hand or detected, in order; a book without them is read as English
def languages_in(metadata_version_id: int | None) -> list[str]:
    if metadata_version_id is None:
        return ["en"]
    with Session() as session:
        found = session.scalar(select(MetadataField.value).where(
            MetadataField.metadata_version_id == metadata_version_id, MetadataField.name == "languages"))
    values = found if isinstance(found, list) else [found] if found else []
    return list(dict.fromkeys(str(v).lower()[:2] for v in values)) or ["en"]


# outside a run the book is read with its current metadata; a run reads with the version it pinned
def languages_of(book_id: int) -> list[str]:
    version = resolve.current_version(book_id)
    return languages_in(version.id if version is not None else None)


# a number in any language: digits, a Roman numeral of two letters or more, or one set off ("I.", "Part I:", "Глава V")
_ROMAN = numerals.ROMAN_LABEL_UPPER
NUMBERED = re.compile(rf"\d|\b(?=[IVXLC]{{2}}){_ROMAN}\b|^{_ROMAN}[.:)]|\b{_ROMAN}(?:[.:)]|$)")
EDGE_SHARE = 0.15
# a lone appendix letter ends the title or takes a colon; "Pedro A. de Miguel" is an initial
LONE_LETTER = re.compile(r"\s*(?::|$)")
# a letter as a chapter's number: "Appendix A:", "appendix B", "A Debugging"
LETTERED = re.compile(r"^(?:(?P<word>[^\W\d_]+)\s+)?(?P<letter>[A-Z])(?:[.:)]|\s|$)")


# chapters are toc rows of kind chapter or front matter with their sections; a part's own pages are one
def chapters_of(rows: list[dict], cut: frozenset[int] = frozenset()) -> list[dict]:
    out = []
    for i, row in enumerate(rows):
        # a row whose pages are all printed contents pages is not a chapter: the toc is built another way
        if all(p in cut for p in range(row["first_page"], row["last_page"] + 1)):
            continue
        if row["kind"] in ("chapter", "front_matter"):
            subs = []
            for nxt in rows[i + 1:]:
                if nxt["kind"] != "section":
                    break
                subs.append((nxt["title"], nxt["level"]))
            out.append({**row, "subs": subs})
        elif row["kind"] == "part":
            first_child = next((r["first_page"] for r in rows[i + 1:] if r["kind"] in ("chapter", "section")), None)
            if first_child is not None and first_child > row["first_page"]:
                out.append({**row, "last_page": first_child - 1, "subs": []})
    pages = max((r["last_page"] for r in rows), default=0)
    # neighbours meeting on a page share it, and each chapter is told the other's title to cut it at
    for prev, nxt in zip(out, out[1:], strict=False):
        if nxt["first_page"] == prev["last_page"]:
            prev["next_title"], nxt["shared_start"] = nxt["title"], True
    return [{"next_title": None, "shared_start": False, **c, "role": role}
            for c, role in zip(out, roles(out, pages), strict=True)]


# the unnumbered chapters before the first numbered one and after the last (a preface, an index) are the book's service
def roles(chapters: list[dict], pages: int) -> list[str]:
    labelled = scan.labels([c["title"] for c in chapters])
    lettered = _lettered([c["title"] for c in chapters])
    numbered = [i for i, c in enumerate(chapters) if NUMBERED.search(c["title"]) or i in lettered
                or (m := scan.STYLE_LABELLED.match(c["title"].strip())) and m.group(1).lower() in labelled]
    # numbering that starts deep in the book means its chapters are unnumbered, not that they are a preface
    if not numbered or chapters[numbered[0]]["first_page"] > EDGE_SHARE * pages:
        return ["body"] * len(chapters)
    first, last = numbered[0], numbered[-1]
    # numbering that ends early leaves unnumbered chapters after it, not back matter
    if pages - chapters[last]["last_page"] > EDGE_SHARE * pages:
        last = len(chapters) - 1
    return ["service" if i < first or i > last else "body" for i in range(len(chapters))]


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


# a chapter's book pages split at file boundaries and around cut pages, as (file, first and last page in that file)
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


# the printed contents pages the toc version found; the bundle leaves them out, they repeat the toc
def _contents_pages(toc_version_id: int) -> frozenset[int]:
    with Session() as session:
        found = (evidence.read(session, toc_version_id) or {}).get("printed_contents") or {}
    return frozenset((found.get("notes") or {}).get("pages") or [])


# the book's first page before the first real toc row is a cover or a title page, which metadata reads instead
def _cover(rows: list[dict]) -> frozenset[int]:
    first = next((r["first_page"] for r in rows if r["kind"] != "front_matter"), 1)
    return frozenset({1}) if first > 1 else frozenset()


# the pages the bundle leaves out, by why: printed contents and the cover
def cut_pages(toc_version_id: int, rows: list[dict]) -> dict[str, frozenset[int]]:
    return cut_of(rows, _contents_pages(toc_version_id))


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


# a chapter's file ranges split again where the regime changes, as (file, first, last, regime)
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


# a name of its own, so door tests stand a build in for the chapter readings only
_build = reading.build


# a reading is kept per file range, fields and engine build, so a rerun of the chapter reads nothing again
def _reading(book_id: int, f: BookFile, a: int, b: int, engine: str, languages: list[str],
             regime: str = "text_pdf") -> Artifact:
    given = reading.fields(engine, regime, languages)
    build = _build(engine)
    made_from = artifacts.Inputs({"stage": STAGE, "file": f.sha256, "pages": [a, b], "fields": given,
                                  "build": build})
    owner = artifacts.Owner(book_id=f.book_id)
    name = f"reading.{engine}.{f.ord}.{a}-{b}{'' if regime == 'text_pdf' else '.' + regime}.json"
    done = artifacts.find_done(owner, STAGE, name, made_from.key)
    if done is not None:
        return done
    started = time.perf_counter()
    structure = reading.read(engine, settings.DATA_DIR / f.file_path, a, b, given, READ_CEILING, build)
    # the reading's own cost, so a run that takes it from the cache still reports what the book took to read
    return artifacts.write(owner, artifacts.book_dir(book_id), STAGE, name, structure, made_from, heavy=True,
                           meta={"engine": engine, "seconds": round(time.perf_counter() - started, 2)})


def _structure(book_id: int, f: BookFile, a: int, b: int, engine: str, languages: list[str],
               regime: str = "text_pdf") -> dict:
    return converter_tools.kept_json(_reading(book_id, f, a, b, engine, languages, regime))


# the key a chapter's read jobs name their readings by, so the assembly takes exactly what was read
def reading_key(engine: str, f: BookFile, a: int, b: int, regime: str) -> str:
    return f"{engine}:{f.ord}:{a}-{b}:{regime}"


# one engine over a chapter's file ranges, each reading kept; the run reads engine by engine so the card moves twice
def read(book_id: int, engine: str, first_page: int, last_page: int, languages: list[str] | None = None,
         cut: frozenset[int] = frozenset()) -> dict[str, int]:
    languages = languages or languages_of(book_id)
    return {reading_key(engine, f, a, b, regime): _reading(book_id, f, a, b, engine, languages, regime).id
            for f, a, b, regime in ranges(book_id, first_page, last_page, cut)}


# the book's running heads by book page, read once from the whole text layer and kept for every chapter
def running(book_id: int) -> dict[int, list[str]]:
    files = intake.files_of(book_id)
    made_from = artifacts.Inputs({"stage": STAGE, "files": [f.sha256 for f in files],
                                  "code": code_version.files_hash([Path(running_heads.__file__)]).hexdigest()[:16]})
    owner = artifacts.Owner(book_id=book_id)
    done = artifacts.find_done(owner, STAGE, "running_heads.json", made_from.key)
    if done is not None:
        return {int(k): v for k, v in json.loads(artifacts.read(done)).items()}
    lines = sources.book_lines(files)
    heads = running_heads.layer_heads(lines)
    artifacts.write(owner, artifacts.book_dir(book_id), STAGE, "running_heads.json", heads, made_from)
    return heads


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


# the readings the chapter's read jobs named, or, without them (an evaluation), the ones kept for today's key
def _kept(book_id: int, f: BookFile, a: int, b: int, regime: str, engine: str, languages: list[str],
          readings: dict[str, int] | None) -> dict:
    if readings is None:
        return _structure(book_id, f, a, b, engine, languages, regime)
    key = reading_key(engine, f, a, b, regime)
    with Session() as session:
        row = session.get(Artifact, readings[key]) if key in readings else None
    if row is None:
        raise Final(f"no {engine} reading of file {f.ord} pages {a}-{b} ({regime}) among this round's reads")
    # a kept reading passes the text cleaning of today's code, as the toc and metadata stages read theirs
    return converter_tools.kept_json(row)


def _range_blocks(book_id: int, f: BookFile, a: int, b: int, regime: str, languages: list[str], got: Assembled,
                  counts: dict, keep: Callable[[bytes], str], knobs: dict | None = None,
                  readings: dict[str, int] | None = None) -> list:
    path = settings.DATA_DIR / f.file_path
    reads = {e: reading.adapt(e, _kept(book_id, f, a, b, regime, e, languages, readings), file_ord=f.ord,
                              book_page=lambda page, f=f: f.first_page + page - 1) for e in ENGINES}
    ranged: list = []
    if regime == "scan":
        scan_engine = {**passes.conf(), **(knobs or {})}["scan_engine"]
        blocks, found, agreement = passes.recognised(reads, scan_engine, ranged,
                                                     chapter_quality.conf()["layer_min_words"])
        got.recognised.update({f.first_page + page - 1: share for page, share in agreement.items()})
        got.pages.update({f.first_page + page - 1: {"picked": scan_engine, "agreement": share}
                          for page, share in agreement.items()})
    else:
        layer = {i + 1: t for i, t in pdf.page_texts(path, list(range(a - 1, b))).items()}
        got.layer.update({f.first_page + page - 1: text for page, text in layer.items()})
        glyphs = cache(lambda page: pdf.page_glyphs(path, page - 1))
        picks: dict = {}
        blocks, found = passes.apply(reads, layer, glyphs, ENGINES, ranged, knobs, picks)
        got.pages.update({f.first_page + page - 1: picked for page, picked in picks.items()})
    got.steps.append({"file": f.ord, "pages": [a, b], "regime": regime, "steps": ranged})
    for key, n in found.items():
        counts[key] = counts.get(key, 0) + n
    # running heads and folios each engine set aside, counted for the chapter's report
    for engine, r in reads.items():
        counts[f"furniture_{engine}"] = counts.get(f"furniture_{engine}", 0) + len(r.furniture)
        got.furniture.setdefault(engine, []).extend(r.furniture)
    return _kept_figures(path, blocks, keep)


# the chapter's own heading is written by the writer, so the toc level is the chapter's place in the book
def assemble(book_id: int, ord: int, title: str, level: int, first_page: int, last_page: int,
             subs: list[tuple[str, int]] = (), languages: list[str] | None = None,
             cut: frozenset[int] = frozenset(), role: str = "body", knobs: dict | None = None,
             readings: dict[str, int] | None = None, shared_start: bool = False,
             next_title: str | None = None) -> Assembled:
    got = Assembled(None, "")
    counts = got.counts

    def keep(png: bytes) -> str:
        name = f"images/{ord:02d}-{len(got.images) + 1:03d}.png"
        got.images[name] = png
        return name

    languages = languages or languages_of(book_id)
    blocks = []
    for f, a, b, regime in ranges(book_id, first_page, last_page, cut):
        blocks += _range_blocks(book_id, f, a, b, regime, languages, got, counts, keep, knobs, readings)
    counts["pages_cut"] = sum(first_page <= p <= last_page for p in cut)
    heads = running(book_id)
    got.furniture["layer"] = [text for page in got.layer for text in heads.get(page, [])]
    toc_level = min(max(level, 1), 5)
    blocks, shared = passes.shared_pages(blocks, title, shared_start, next_title)
    counts.update(shared)
    blocks, counts["title_dropped"] = passes.without_title(blocks, title)
    blocks, levelled = passes.chapter_levels(blocks, toc_level, list(subs))
    counts.update(levelled)
    got.chapter = Chapter(ord=ord, title=title, level=toc_level, first_page=first_page, last_page=last_page,
                          role=role, blocks=blocks)
    got.markdown = markdown.chapter(got.chapter)
    return got
