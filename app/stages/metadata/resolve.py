# every source runs for every field; the value comes from the highest-ranked source that has it
import json
import re
from dataclasses import asdict

import artifacts
import book_knobs
import code_version
import model_steps
import pdf
import settings
import yaml
from engines import card, reading
from job_signals import Deferred
from orm.catalogue import MetadataField, MetadataVersion
from orm.db import Session
from sqlalchemy import select

from stages import book_stage, intake, versions
from stages.metadata import file_metadata, language, model_reader, title_pages
from stages.metadata.candidates import FIELDS, OPTIONAL, Candidate, SourceResult

STAGE = "metadata"
BODY_SAMPLE_PAGES = 20
# every value comes from the book itself: its files, its title pages, and the stand's model reading them
DEFAULT_RANK = ("manual", "title_pages", "model", "detector", "intake", "file_metadata")
RANK = {
    "languages": ("manual", "detector", "model"),
    "isbn": ("manual", "title_pages", "model"),
    "edition": ("manual", "model"),
    "volume": ("manual", "model"),
    "pages": ("manual", "intake"),
    "publisher": ("manual", "model", "file_metadata"),
    "original_title": ("manual", "title_pages", "model"),
    "subject": ("manual", "model"),
    "made_with": ("manual", "file_metadata"),
}
# recognised pages carry their pictures inline as base64, which reads as text to every later step
INLINE_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")


def without_images(markdown: str) -> str:
    return INLINE_IMAGE.sub("", markdown)


def window(book_id: int) -> tuple[int, int]:
    knobs = book_knobs.of(book_id)
    return knobs["metadata.title_pages.head"], knobs["metadata.title_pages.tail"]


def _rank(field: str) -> tuple[str, ...]:
    return RANK.get(field, DEFAULT_RANK)


def code_hash() -> str:
    # metadata reads title pages through the layer reader, so the reader is its code too
    digest = code_version.files_hash([*sorted((settings.APP_DIR / "stages" / "metadata").glob("*.py")),
                                     settings.APP_DIR / "model_steps.py", settings.APP_DIR / "pdf.py"])
    # only the metadata's own model steps: a step another stage adds does not make metadata stale
    steps = model_steps.steps()
    digest.update(json.dumps({k: steps[k] for k in ("metadata_reader", "subject")}, sort_keys=True).encode())
    for name in ("metadata.yaml", "isbn_groups.yaml"):
        digest.update((settings.CONFIG_DIR / name).read_bytes())
    return digest.hexdigest()[:16]


def current_version(book_id: int) -> MetadataVersion | None:
    with Session() as session:
        return versions.current(session, MetadataVersion, book_id)


def _manual(version: MetadataVersion | None) -> SourceResult:
    out = SourceResult("manual", covers=FIELDS)
    if version is None:
        return out
    with Session() as session:
        for f in session.scalars(select(MetadataField).where(MetadataField.metadata_version_id == version.id,
                                                             MetadataField.source == "manual")):
            out.add(f.name, f.value, 1.0, "set by hand")
    return out


# a book whose title pages MinerU reads is stale when its build changes, as when the code does
def inputs(book_id: int, manual: SourceResult) -> artifacts.Inputs:
    files = intake.files_of(book_id)
    parts = {"stage": STAGE, "code": code_hash(), "files": [f.sha256 for f in files],
             # only the knobs set on the book, as the toc keys: a new knob at its default stales no book
             "knobs": {k: v for k, v in book_knobs.overrides(book_id).items() if k.startswith("metadata.")},
             "manual": [(c.field, c.value) for c in manual.candidates]}
    window_text = _title_window(book_id)
    if not pdf.has_layer(window_text) or pdf.garbled(window_text):
        parts["mineru"] = reading.build("mineru")
    return artifacts.Inputs(parts)


def _title_window(book_id: int) -> str:
    files = intake.files_of(book_id)
    first, last = files[0], files[-1]
    head_n, tail_n = window(book_id)
    head = pdf.page_texts(settings.DATA_DIR / first.file_path, list(range(head_n)))
    tail = pdf.page_texts(settings.DATA_DIR / last.file_path, list(range(last.pages - tail_n, last.pages)))
    return "\n".join(head[i] for i in sorted(head)) + "\n" + "\n".join(tail[i] for i in sorted(tail))


def _title_and_body(book_id: int) -> tuple[str, str, bool]:
    files = intake.files_of(book_id)
    first, last = files[0], files[-1]
    head_n, tail_n = window(book_id)
    title = _title_window(book_id)
    scanned = not pdf.has_layer(title) or pdf.garbled(title)
    if scanned:
        title = _recognised_title_pages(book_id, first, last)
    body_pages, sampled = [], 0
    total = sum(f.pages for f in files)
    for f in files:
        step = max(1, f.pages // BODY_SAMPLE_PAGES)
        # a short book is all title window; its body sample starts after the first pages instead
        start = head_n if total > head_n + tail_n + BODY_SAMPLE_PAGES else min(3, f.pages - 1)
        texts = pdf.page_texts(settings.DATA_DIR / f.file_path, list(range(start, f.pages, step)))
        sampled += len(texts)
        body_pages += [t for t in texts.values() if pdf.has_layer(t) and not pdf.garbled(t)]
    # a book whose layer is mostly broken speaks through its recognised pages, not through the few left over
    if scanned and len(body_pages) * 2 < sampled:
        body_pages = []
    body = "\n".join(body_pages) or title
    return title, body, scanned


# a scan's title pages are recognised once and kept, so a recollection does not redo it
OCR_FIELDS = [("tier", "standard"), ("ocr_mode", "ocr"), ("output_formats", ["markdown"])]


# keyed by the files, the window, the request and the engine build: a new image or request reads again
def _recognised_title_pages(book_id: int, first, last) -> str:
    from engines import converter_tools

    owner = artifacts.Owner(book_id=book_id)
    head_n, tail_n = window(book_id)
    build = reading.build("mineru")
    ocr_inputs = artifacts.Inputs({"stage": "title_pages_ocr", "first": first.sha256, "last": last.sha256,
                                   "window": [head_n, tail_n], "fields": OCR_FIELDS, "build": build})
    done = artifacts.find_done(owner, STAGE, "title_pages.md", ocr_inputs.key)
    if done is not None:
        return without_images(converter_tools.kept_text(done))
    # a failed or timed-out reading raises and is never cached as an empty page: the job retries instead
    parts = [reading.read_markdown("mineru", settings.DATA_DIR / f.file_path, a, b, OCR_FIELDS, 900, build)
             for f, a, b in ((first, 1, min(head_n, first.pages)), (last, max(1, last.pages - tail_n + 1), last.pages))]
    text = without_images("\n".join(parts))
    artifacts.write(owner, artifacts.book_dir(book_id), STAGE, "title_pages.md", text, ocr_inputs,
                    meta={"engine": "mineru", "build": build, "fields": OCR_FIELDS})
    return text


def isbn_groups() -> dict[str, tuple[str, ...]]:
    conf = yaml.safe_load((settings.CONFIG_DIR / "isbn_groups.yaml").read_text())["groups"]
    return {lang: tuple(prefixes) for lang, prefixes in conf.items()}


def _in_groups(isbn: str, language: str) -> bool:
    value = str(isbn)
    if len(value) == 10:
        value = "978" + value
    return value.startswith(isbn_groups().get(language, ()))


# a translation prints the original's ISBN too; the book's own is the first one in its language's group
def _own_isbn(found: SourceResult, languages: list[str]) -> None:
    isbns = [c for c in found.candidates if c.field in ("isbn", "_other_isbn")]
    if not languages or len(isbns) < 2:
        return
    local = [c for c in isbns if _in_groups(c.value, languages[0])]
    if not local:
        return
    for c in isbns:
        if c is local[0]:
            c.field, c.evidence = "isbn", c.evidence + f"; in the {languages[0]} registration group"
        elif c.field == "isbn":
            c.field = "_other_isbn"


# a translation's title pages show the original's title too; the title is the one in the text's language
def _title_in_book_language(results: list[SourceResult], book_language: str | None) -> None:
    if not book_language:
        return
    titles = [c for r in results for c in r.candidates if c.field == "title"]
    languages = {id(c): language.of_line(str(c.value)) for c in titles}
    if not any(lang == book_language for lang in languages.values()):
        return
    for c in titles:
        lang = languages[id(c)]
        if lang and lang != book_language:
            c.field = "original_title"
            c.evidence += f"; a title in {lang}, the book is in {book_language}"


def gather(book_id: int, manual: SourceResult) -> list[SourceResult]:
    files = intake.files_of(book_id)
    title, body, scanned = _title_and_body(book_id)
    results = [manual]
    results.append(file_metadata.read([pdf.info(settings.DATA_DIR / f.file_path) for f in files],
                                      [f.file_name for f in files],
                                      [pdf.xmp(settings.DATA_DIR / f.file_path) for f in files]))
    pages = SourceResult("intake", covers=("pages",))
    pages.add("pages", sum(f.pages for f in files), 1.0, "page count of the files")
    results.append(pages)
    lang = language.read(body)
    results.append(lang)
    found = title_pages.read(title)
    _own_isbn(found, next((c.value for c in lang.candidates), []))
    results.append(found)
    results.append(model_reader.read(title))
    best_title = _best("title", results)
    book_language = next(iter(_best("languages", results) or []), None)
    results.append(_subject(best_title, title, body))
    _title_in_book_language(results, book_language)
    return results


def _subject(title, title_text: str, body: str) -> SourceResult:
    try:
        return model_reader.subject(title, title_text[:4000] + body[:2000], title_text[-2000:])
    # a model that is away is waited for, and one that needs the card goes to its lane, not recorded as empty
    except (Deferred, card.WrongLane):
        raise
    except Exception as e:
        out = SourceResult("model", covers=("subject",))
        out.failed = str(e)
        return out


# a cover set in capitals ("МАЛЬЧИК С КОНЬКАМИ") reads as a sentence; short all-caps titles may be acronyms
def uncapped(title: str) -> str:
    letters = [c for c in title if c.isalpha()]
    if len(letters) < 8 or not all(c.isupper() for c in letters):
        return title
    return title[:1] + title[1:].lower()


def _norm(value) -> str:
    if isinstance(value, list):
        return "|".join(sorted(str(v).strip().lower() for v in value))
    return str(value).strip().lower()


def _best(field: str, results: list[SourceResult]):
    pick = _pick(field, results)
    return pick.value if pick else None


def _pick(field: str, results: list[SourceResult]) -> Candidate | None:
    candidates = [c for r in results for c in r.candidates if c.field == field]
    ranked = [c for source in _rank(field) for c in candidates if c.source == source]
    return ranked[0] if ranked else None


def resolve(results: list[SourceResult]) -> list[dict]:
    rows = []
    for field in FIELDS:
        pick = _pick(field, results)
        attempts = []
        for r in results:
            mine = [c for c in r.candidates if c.field == field]
            if r.source not in _rank(field) and not mine:
                continue
            if mine:
                outcome = "found"
                if pick is not None and any(_norm(c.value) != _norm(pick.value) for c in mine):
                    outcome = "conflict"
                attempts.append({"source": r.source, "outcome": outcome, "values": [c.value for c in mine],
                                 "evidence": [c.evidence for c in mine]})
            elif r.failed:
                attempts.append({"source": r.source, "outcome": "failed", "detail": r.failed})
            elif field in r.covers:
                attempts.append({"source": r.source, "outcome": "absent"})
        confidence = None
        if pick is not None:
            conflicts = sum(a["outcome"] == "conflict" for a in attempts)
            confidence = round(pick.confidence * (0.7 if conflicts else 1.0), 2)
        if pick is not None and field == "title" and isinstance(pick.value, str):
            pick = Candidate(pick.field, uncapped(pick.value), pick.source, pick.confidence, pick.evidence)
        rows.append({"name": field, "optional": field in OPTIONAL,
                     "value": pick.value if pick else None, "source": pick.source if pick else None,
                     "confidence": confidence, "attempts": attempts or [{"source": "none", "outcome": "absent"}]})
    return rows


def collect(book_id: int, job_id: int | None = None, force: bool = False) -> int:
    previous = current_version(book_id)
    manual = _manual(previous)
    made_from = inputs(book_id, manual)
    # a version whose evidence never got written is not fresh: its artifacts follow the commit
    kept = previous is not None and artifacts.find_done(artifacts.Owner(metadata_version_id=previous.id), STAGE,
                                                       "fields.json", made_from.key) is not None
    if kept and previous.input_hash == made_from.key and not force:
        return previous.id
    results = gather(book_id, manual)
    rows = resolve(results)
    return write_version(book_id, made_from, rows, job_id, {"sources": [asdict(r) for r in results]})


def _store_version(session, book_id: int, key: str, rows: list[dict], job_id: int | None) -> tuple[int, int]:
    version = versions.new(session, MetadataVersion, book_id, key, job_id)
    number = version.version
    for row in rows:
        session.add(MetadataField(metadata_version_id=version.id, **{k: v for k, v in row.items() if k != "optional"}))
    session.flush()
    book_stage.settle(session, book_id)
    return version.id, number


def _version_artifacts(book_id: int, version_id: int, number: int, made_from: artifacts.Inputs, rows: list[dict],
                       evidence: dict) -> None:
    owner = artifacts.Owner(metadata_version_id=version_id)
    base = artifacts.version_dir(book_id, "metadata", number)
    artifacts.write(owner, base, STAGE, "sources.json", json.loads(json.dumps(evidence, default=str)), made_from)
    artifacts.write(owner, base, STAGE, "fields.json", rows, made_from)


def write_version(book_id: int, made_from: artifacts.Inputs, rows: list[dict], job_id: int | None,
                  evidence: dict) -> int:
    with Session() as session:
        versions.lock_book(session, book_id)
        version_id, number = _store_version(session, book_id, made_from.key, rows, job_id)
        session.commit()
    _version_artifacts(book_id, version_id, number, made_from, rows, evidence)
    return version_id


# a hand-set value: read and written under one lock, and stamped so that the next collection runs again
MANUAL_STAMP = "manual-edit:"


def set_manual(book_id: int, name: str, value) -> int:
    with Session() as session:
        versions.lock_book(session, book_id)
        current = versions.current(session, MetadataVersion, book_id)
        if current is None:
            raise LookupError(f"book {book_id} has no metadata yet")
        rows = []
        for f in session.scalars(select(MetadataField).where(MetadataField.metadata_version_id == current.id)):
            row = {"name": f.name, "value": f.value, "source": f.source, "confidence": f.confidence,
                   "attempts": f.attempts}
            if f.name == name:
                found = [a for a in f.attempts if a.get("source") != "manual"]
                if f.value is not None and f.source != "manual":
                    found.append({"source": f.source, "outcome": "found", "values": [f.value],
                                  "evidence": ["replaced by a manual value"]})
                row = {"name": name, "value": value, "source": "manual", "confidence": 1.0,
                       "attempts": [{"source": "manual", "outcome": "found", "values": [value]}, *found]}
            rows.append(row)
        # never equal to a computed key: the copied values came from older code and knobs
        made_from = artifacts.Inputs({"previous": current.input_hash, "manual": {name: value}},
                                     stamp=MANUAL_STAMP + current.input_hash)
        version_id, number = _store_version(session, book_id, made_from.key, rows, None)
        session.commit()
    _version_artifacts(book_id, version_id, number, made_from, rows, {"manual": {name: value}})
    return version_id


# a version made from other inputs than today's (code, knobs, files, model steps) is stale and is collected again
def stale(book_id: int) -> bool:
    previous = current_version(book_id)
    return previous is not None and previous.input_hash != inputs(book_id, _manual(previous)).key
