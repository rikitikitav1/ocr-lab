# the book's structure as node page ranges; with no contents a short book is one node, a long one is not recognised
import json
from dataclasses import asdict, replace
from pathlib import Path

import artifacts
import book_knobs
import code_version
import model_steps
import numerals
import settings
import text_layer
from job_signals import Final
from orm.catalogue import Book, StructureNode, StructureVersion
from orm.db import Session
from structure import tree

from stages import book_stage, intake, versions
from stages.metadata import resolve
from stages.structure import outlines, pages, reconcile, scan
from stages.structure.sources import (
    Entry,
    SourceEntries,
    book_lines,
    bookmarks,
    conf,
    files,
    headings,
    labelled,
    numbering,
    printed_contents,
)
from stages.structure.sources.numbering import title_depth

STAGE = "structure"


def code_hash() -> str:
    # the structure reads the layer, running heads and numerals, so the code that reads them is its code
    own = [*sorted((settings.APP_DIR / "stages" / "structure").rglob("*.py")), settings.APP_DIR / "model_steps.py",
           settings.APP_DIR / "elements" / "running_heads.py", settings.APP_DIR / "numerals.py",
           settings.APP_DIR / "structure" / "tree.py", settings.APP_DIR / "alphabets.py"]
    digest = code_version.files_hash(own, ("structure.yaml",))
    digest.update(json.dumps(model_steps.steps()["contents_reader"], sort_keys=True).encode())
    return digest.hexdigest()[:16]


# a book whose contents MinerU reads is stale when its build changes, as when the code does
def inputs(book_id: int) -> artifacts.Inputs:
    # only the book's own structure knobs: a new knob at its default, or the reading level, leaves a structure fresh
    knobs = {k: v for k, v in book_knobs.overrides(book_id).items()
             if k.startswith("structure.") and k != "structure.reading_level"}
    # the book's languages tell a broken layer's headings, so a new language list collects the structure again
    parts = {"stage": STAGE, "code": code_hash(), "files": [f.sha256 for f in intake.files_of(book_id)],
             "knobs": knobs, "languages": resolve.known_languages_of(book_id)}
    if scanned(book_id) or scan.raster_contents(book_id, knobs.get("structure.contents_pages"), run=False) is not None:
        from engines import reading

        parts["mineru"] = reading.build("mineru")
    return artifacts.Inputs(parts)


def current_version(book_id: int) -> StructureVersion | None:
    with Session() as session:
        return versions.current(session, StructureVersion, book_id)


def _printed(files, given, lines: dict) -> tuple[SourceEntries, dict]:
    found = printed_contents.read(files, given)
    if found.failed or not found.entries:
        return found, {}
    text = pages.page_text(lines, set(found.notes.get("pages", [])))
    return found, pages.place(found.entries, text, sum(f.pages for f in files))


def _whole_book(files) -> Entry:
    return Entry(Path(files[0].file_name).stem, 1, 1, evidence="no contents in a short book: one node",
                 source="whole_book")


def scanned(book_id: int) -> bool:
    with Session() as session:
        return scan.is_scan(session.get(Book, book_id))


# a knob for books whose first top bookmark is the book itself: it goes, and the entries under it rise a level
def without_root(entries: list[Entry]) -> list[Entry]:
    if len(entries) < 2 or entries[1].level <= entries[0].level:
        return entries
    root, out, inside = entries[0], [], True
    for e in entries[1:]:
        inside = inside and e.level > root.level
        out.append(replace(e, level=e.level - 1) if inside else e)
    return out


# the bookmarks as every reader of them sees them, after the book's bookmark knobs
def book_bookmarks(book_files, knobs: dict) -> SourceEntries:
    if knobs["structure.ignore_bookmarks"]:
        return SourceEntries("bookmarks", failed="ignored by the book knob structure.ignore_bookmarks")
    marks = bookmarks.read(book_files)
    if knobs["structure.skip_root_bookmark"]:
        marks.entries = without_root(marks.entries)
    return marks


# no readable contents in the text layer, no bookmarks or chapter files to stand for them, raster never read
def needs_raster(book_id: int) -> bool:
    if scanned(book_id):
        return False
    knobs = book_knobs.of(book_id)
    given = knobs["structure.contents_pages"]
    book_files = intake.files_of(book_id)
    pages_found, lines = printed_contents.find_pages(book_files, given)
    text = " ".join(x.text for p in pages_found for x in lines.get(p, []))
    # contents pages the owner named but that are pictures are read by recognition
    if pages_found and (not given or (text_layer.has_layer(text) and not text_layer.garbled(text))):
        return False
    if len([e for e in book_bookmarks(book_files, knobs).entries if e.page is not None]) >= 2:
        return False
    if len(files.read(book_files).entries) >= 2:
        return False
    return scan.raster_contents(book_id, given, run=False) is None


# a scan, or a text book whose layer gave no contents, has its structure read from the raster on the GPU lane
def wants_raster(book_id: int) -> bool:
    return scanned(book_id) or needs_raster(book_id)


# all sources reconciled; `off` leaves sources out, `raster` lets a text book's contents be recognised
def choose(book_id: int, off: tuple[str, ...] = (), raster: bool = False) -> tuple[str, list[Entry], dict]:
    book_files = intake.files_of(book_id)
    total = sum(f.pages for f in book_files)
    knobs = book_knobs.of(book_id)
    marks = SourceEntries("bookmarks", failed="switched off") \
        if "bookmarks" in off and not knobs["structure.ignore_bookmarks"] else book_bookmarks(book_files, knobs)
    given = knobs["structure.contents_pages"]
    label = knobs["structure.chapter_label"]
    if scanned(book_id):
        printed, placement = scan.read(book_id, given)
        counted = SourceEntries("numbering", failed="a scan has no text to count numbers in")
        heads = scan.top_blocks(book_id, total) if label else {}
    else:
        lines = book_lines(book_files)
        first = conf()["text_layer"]["numbering"]["head_lines"]
        heads = {p: [x.text for x in ls[:first]] for p, ls in lines.items()} if label else {}
        printed, placement = _printed(book_files, given, lines)
        if not printed.entries and (seen := scan.raster_contents(book_id, given, run=raster)) and seen.entries:
            printed = seen
            text = pages.page_text(lines, set(seen.notes["pages"]))
            placement = pages.place(seen.entries, text, total)
        counted = numbering.read(book_files, set(printed.notes.get("pages", [])), lines)
    by_file = files.read(book_files)
    found = {s.source: s.entries for s in (marks, printed, by_file, counted) if s.source not in off}
    styled = _styled(found, lines if not scanned(book_id) else None, total, frozenset(printed.notes.get("pages") or []),
                     off, bool(label), book_id)
    if styled.entries:
        found[styled.source] = styled.entries
    base, merged, report = reconcile.reconcile(found)
    evidence = {"pages": total, "bookmarks": asdict(marks), "printed_contents": asdict(printed),
                "placement": placement, "files": asdict(by_file), "numbering": asdict(counted),
                "text_headings": asdict(styled), "reconcile": report}
    if base is not None:
        if not scanned(book_id) and "outlines" not in off:
            found_pages = frozenset(printed.notes.get("pages") or [])
            merged, evidence["outlines"] = outlines.fold(merged, lines, measured_offset(placement or {}), total,
                                                         found_pages)
        return base, merged, evidence
    if label:
        labels = labelled.read(heads, label, "a recognised page" if scanned(book_id) else "the text layer")
        evidence["labels"] = asdict(labels)
        if not labels.failed:
            return "labels", labels.entries, evidence
    # nothing else holds the book's contents (an ebook's outline was all it had): its labelled chapters in the text are
    if "numbering" not in off and _labelled(counted.entries) >= conf()["text_layer"]["numbering_base_min"]:
        dropped = _out_of_turn(counted.entries)
        evidence["numbering_out_of_turn"] = [e.title for e in dropped]
        return "numbering", [e for e in counted.entries if not any(e is d for d in dropped)], evidence
    # a word the text repeats before its chapters' numbers ("Глава осма") gives them, however the layer runs lines
    if not scanned(book_id) and "labels" not in off and (seen := labelled.found_in(book_files, lines)) is not None:
        evidence["labels"] = asdict(seen)
        return "labels", seen.entries, evidence
    if knobs["structure.from_headings"] and "headings" not in off:
        seen = headings.read(scan.recognise(book_id, list(range(1, total + 1))), total, scan._text,
                             frozenset(printed.notes.get("pages") or []))
        evidence["headings"] = asdict(seen)
        if not seen.failed:
            return "headings", seen.entries, evidence
    if total <= conf()["whole_book_max_pages"]:
        return "whole_book", [_whole_book(book_files)], evidence
    # a text layer whose headings were read and refused says why, a broken layer above all
    styled_tried = f", text headings {styled.failed}" if styled.notes and styled.failed else ""
    tried = styled_tried + (f", headings {evidence['headings']['failed']}" if "headings" in evidence else "")
    raise Final(f"structure not recognised: no structure found in a book of {total} pages: "
                f"bookmarks {marks.failed or 'too few'}, "
                f"printed contents {printed.failed or 'too few placed'}{tried}")


# a text book no contents source holds reads its chapters from the headings its text layer sets apart
def _styled(found: dict, lines: dict | None, total: int, contents: frozenset[int], off: tuple[str, ...],
            labelled_by_knob: bool, book_id: int) -> SourceEntries:
    held = any(len([e for e in entries if e.page is not None]) >= reconcile.MIN_ENTRIES
               for source, entries in found.items() if source not in reconcile.VOTES_ONLY)
    if lines is None or held or labelled_by_knob or "text_headings" in off:
        return SourceEntries("text_headings", failed="not read: a scan, a contents source, the label knob, or off")
    return headings.read_lines(lines, total, contents, tuple(resolve.known_languages_of(book_id)))


# chapters opening on neighbouring pages are a list of them (a contents page, a series page), not the book's chapters
NEIGHBOURS = 0.3
# a chapter number met again out of turn is a cross-reference set like a heading; a few of them are tolerated
BACKWARDS = 0.1


def _number(entry: Entry, kind: str) -> int | None:
    m = numbering.label_pattern(kind).match(entry.title.strip())
    return numerals.value(m.group("num")) if m else None


# labelled entries outside the longest rising run of their kind's numbers are cross-references set like headings
def _out_of_turn(entries: list[Entry]) -> list[Entry]:
    out = []
    for kind in ("part", "chapter"):
        numbered = [(e, n) for e in entries if (n := _number(e, kind)) is not None]
        best = [1] * len(numbered)
        for i in range(len(numbered)):
            for j in range(i):
                if numbered[j][1] < numbered[i][1]:
                    best[i] = max(best[i], best[j] + 1)
        keep, length, last = set(), max(best, default=0), None
        for i in range(len(numbered) - 1, -1, -1):
            if best[i] == length and (last is None or numbered[i][1] < last):
                keep.add(i)
                length, last = length - 1, numbered[i][1]
        out += [e for i, (e, _) in enumerate(numbered) if i not in keep]
    return out


# labelled chapters that can stand as a structure: their numbers rise and they open pages apart
def _labelled(entries: list[Entry]) -> int:
    found = [e for e in entries if title_depth(e.title) in (-1, 0)]
    if len(_out_of_turn(found)) > BACKWARDS * max(1, len(found) - 1):
        return 0
    # a part's page and its first chapter's page are neighbours by design, so each kind is measured among itself
    close = steps = 0
    for depth in (-1, 0):
        pages = [e.page for e in found if e.page is not None and title_depth(e.title) == depth]
        close += sum(b - a <= 1 for a, b in zip(pages, pages[1:], strict=False))
        steps += max(0, len(pages) - 1)
    return 0 if close > NEIGHBOURS * max(1, steps) else len(found)


# the pages before the first entry are a section of their own, so no page of the book is left out of the structure
def with_front_matter(entries: list[Entry], files) -> list[Entry]:
    first = min((e.page for e in entries if e.page is not None), default=1)
    if first <= 1:
        return entries
    top = min((e.level or 1 for e in entries), default=1)
    front = Entry(Path(files[0].file_name).stem, top, 1, evidence=f"the pages before the first entry, 1-{first - 1}",
                  source="front_matter")
    return [front, *entries]


# the rows a structure version stores, the front matter included
def structure_rows(entries: list[Entry], source: str, total: int, files) -> list[dict]:
    return rows(with_front_matter(entries, files), source, total)


# an entry ends where the next one at its level or above starts; one starting on the same page ends there
def rows(entries: list[Entry], source: str, total: int) -> list[dict]:
    top = min(e.level or 1 for e in entries)
    out = []
    for i, e in enumerate(entries):
        level = (e.level or top) - top + 1
        nxt = next((x.page for x in entries[i + 1:] if (x.level or top) <= (e.level or top)), None)
        last = total if nxt is None else max(e.page, nxt - 1)
        out.append({"ord": i + 1, "title": e.title, "level": level, "level_source": e.source or source,
                    "first_page": e.page, "last_page": last,
                    "kind": "front_matter" if e.source == "front_matter" else "node",
                    "votes": e.votes or {source: {"level": e.level, "printed": e.printed, "evidence": e.evidence}}})
    return out


# the offset of the printed contents when the text confirms most entries, or of a scan's page numbers
def measured_offset(placement: dict) -> int | None:
    if placement.get("offset_from") == "page numbers":
        return placement.get("offset")
    tried = placement.get("verified", 0) + placement.get("unverified", 0)
    return placement.get("offset") if tried and placement["verified"] * 2 > tried else None


# each row's parent is the nearest row before it one level up, so the rows form the tree a version stores
def with_parents(rows: list[dict]) -> list[dict]:
    parents = tree.parents([row["level"] for row in rows])
    return [{**row, "parent_ord": None if parent is None else rows[parent]["ord"]}
            for row, parent in zip(rows, parents, strict=True)]


def write_version(book_id: int, made_from: artifacts.Inputs, entries: list[dict], job_id: int | None,
                  evidence: dict) -> int:
    with Session() as session:
        versions.lock_book(session, book_id)
        version = versions.new(session, StructureVersion, book_id, made_from.key, job_id)
        number = version.version
        levels = [row["level"] for row in entries]
        version.depth = tree.depth(levels)
        version.reading_level = tree.reading_level(levels)
        for row in with_parents(entries):
            session.add(StructureNode(structure_version_id=version.id, **row))
        session.flush()
        book_stage.settle(session, book_id)
        book = session.get(Book, book_id)
        book.page_offset = measured_offset(evidence.get("placement") or {})
        # the result is a run on the current structure, and no run is on a version made just now
        book.result_run_id = None
        session.commit()
        version_id = version.id
    owner = artifacts.Owner(structure_version_id=version_id)
    base = artifacts.version_dir(book_id, STAGE, number)
    artifacts.write(owner, base, STAGE, "sources.json", json.loads(json.dumps(evidence, default=str)), made_from)
    artifacts.write(owner, base, STAGE, "nodes.json", entries, made_from)
    return version_id


def collect(book_id: int, job_id: int | None = None, force: bool = False, raster: bool = False) -> int:
    previous = current_version(book_id)
    made_from = inputs(book_id)
    # a version whose evidence never got written is not fresh: its artifacts follow the commit
    kept = previous is not None and artifacts.find_done(artifacts.Owner(structure_version_id=previous.id), STAGE,
                                                       "nodes.json", made_from.key) is not None
    if kept and previous.input_hash == made_from.key and not force:
        return previous.id
    source, entries, evidence = choose(book_id, raster=raster)
    found = structure_rows(entries, source, evidence["pages"], intake.files_of(book_id))
    # keyed after the work: a raster read just kept names MinerU's build, so the version is not stale at once
    return write_version(book_id, inputs(book_id), found, job_id, {"chosen": source, **evidence})


def stale(book_id: int) -> bool:
    previous = current_version(book_id)
    return previous is not None and previous.input_hash != inputs(book_id).key
