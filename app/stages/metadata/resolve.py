# every source runs for every field; the value comes from the highest-ranked source that has it
import hashlib
import json
import re
import unicodedata
from dataclasses import asdict

import artifacts
import book_knobs
import pdf
import settings
import yaml
from job_handlers import Deferred
from orm.catalogue import Book, MetadataField, MetadataVersion
from orm.db import Session
from sqlalchemy import func, select, update

from stages import intake
from stages.metadata import catalogues, file_metadata, language, model_reader, title_pages, web
from stages.metadata.candidates import FIELDS, OPTIONAL, Candidate, SourceResult

STAGE = "metadata"
BODY_SAMPLE_PAGES = 20
CATALOGUES = ("catalogue:labirint", "catalogue:bookvoed", "catalogue:open_library", "catalogue:google_books",
              "catalogue:amazon")
BY_TITLE = ("catalogue:labirint_title", "catalogue:bookvoed_title", "catalogue:open_library_title")
DEFAULT_RANK = ("manual", "imprint", *CATALOGUES, "web", "title_pages", "model", *BY_TITLE, "detector", "intake",
                "file_metadata")
RANK = {
    "languages": ("manual", "detector", "catalogue:labirint", "catalogue:google_books", "model"),
    "isbn": ("manual", "title_pages", "model", "catalogue:amazon", *BY_TITLE),
    "original_isbn": ("manual", "title_pages"),
    "edition": ("manual", "title_pages", "model", *CATALOGUES),
    "volume": ("manual", "title_pages", "model", *CATALOGUES),
    "pages": ("manual", "intake"),
    # a publisher phrase in the text is the weakest reading of the title pages
    "publisher": ("manual", "imprint", *CATALOGUES, "web", "model", "title_pages", *BY_TITLE, "file_metadata"),
    "editions": ("manual", "web"),
    "translators": ("manual", "catalogue:labirint", "catalogue:bookvoed", "title_pages", "model"),
    "illustrators": ("manual", "title_pages", "model"),
    "original_title": ("manual", "title_pages", "model"),
    "original_year": ("manual", "title_pages", "model"),
    "subject": ("manual", "model"),
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
    digest = hashlib.sha256()
    for path in [*sorted((settings.APP_DIR / "stages" / "metadata").glob("*.py")), settings.APP_DIR / "pdf.py"]:
        digest.update(path.read_bytes())
    digest.update((settings.CONFIG_DIR / "models.yaml").read_bytes())
    digest.update((settings.CONFIG_DIR / "metadata.yaml").read_bytes())
    digest.update((settings.CONFIG_DIR / "isbn_groups.yaml").read_bytes())
    digest.update((settings.CONFIG_DIR / "web_sources.yaml").read_bytes())
    return digest.hexdigest()[:16]


def current_version(book_id: int) -> MetadataVersion | None:
    with Session() as session:
        return session.scalar(select(MetadataVersion).where(MetadataVersion.book_id == book_id,
                                                            MetadataVersion.current))


def _manual(version: MetadataVersion | None) -> SourceResult:
    out = SourceResult("manual", covers=FIELDS)
    if version is None:
        return out
    with Session() as session:
        for f in session.scalars(select(MetadataField).where(MetadataField.metadata_version_id == version.id,
                                                             MetadataField.source == "manual")):
            out.add(f.name, f.value, 1.0, "set by hand")
    return out


def input_hash(book_id: int, manual: SourceResult) -> str:
    files = intake.files_of(book_id)
    return artifacts.input_hash(stage=STAGE, code=code_hash(), files=[f.sha256 for f in files],
                                knobs=book_knobs.of(book_id), manual=[(c.field, c.value) for c in manual.candidates])


def _title_and_body(book_id: int) -> tuple[str, str, bool]:
    files = intake.files_of(book_id)
    first, last = files[0], files[-1]
    head_n, tail_n = window(book_id)
    head = pdf.page_texts(settings.DATA_DIR / first.file_path, list(range(head_n)))
    tail = pdf.page_texts(settings.DATA_DIR / last.file_path, list(range(last.pages - tail_n, last.pages)))
    title = "\n".join(head[i] for i in sorted(head)) + "\n" + "\n".join(tail[i] for i in sorted(tail))
    scanned = not pdf.has_layer(title)
    if scanned:
        title = _recognised_title_pages(book_id, first, last)
    body_pages = []
    total = sum(f.pages for f in files)
    for f in files:
        step = max(1, f.pages // BODY_SAMPLE_PAGES)
        # a short book is all title window; its body sample starts after the first pages instead
        start = head_n if total > head_n + tail_n + BODY_SAMPLE_PAGES else min(3, f.pages - 1)
        texts = pdf.page_texts(settings.DATA_DIR / f.file_path, list(range(start, f.pages, step)))
        body_pages += [t for t in texts.values() if pdf.has_layer(t)]
    body = "\n".join(body_pages) or title
    return title, body, scanned


# a scan's title pages are recognised once and kept, so a recollection does not redo it
OCR_FIELDS = [("tier", "standard"), ("ocr_mode", "ocr"), ("output_formats", ["markdown"])]
OCR_KEPT = ("success", "partial_success")


# keyed by the files, the window, the request and the engine build: a new image or request reads again
def _recognised_title_pages(book_id: int, first, last) -> str:
    from engines import card, converter, converter_tools

    owner = artifacts.Owner(book_id=book_id)
    head_n, tail_n = window(book_id)
    try:
        build = converter.build("mineru")
    except converter.WillNotStart as e:
        raise Deferred(f"MinerU cannot say its build: {e}", delay_seconds=300) from e
    key = artifacts.input_hash(stage="title_pages_ocr", first=first.sha256, last=last.sha256, window=[head_n, tail_n],
                               fields=OCR_FIELDS, build=build)
    done = artifacts.find_done(owner, STAGE, "title_pages.md", key)
    if done is not None:
        return without_images(artifacts.read(done).decode())
    card.hand_to("mineru")
    parts = []
    for f, a, b in ((first, 1, min(head_n, first.pages)), (last, max(1, last.pages - tail_n + 1), last.pages)):
        read = converter_tools.mineru(settings.DATA_DIR / f.file_path, OCR_FIELDS, a, b, ceiling=900)
        # a failed or timed-out reading is never cached as an empty page: the job retries instead
        if read.get("status") not in OCR_KEPT:
            raise RuntimeError(f"MinerU read pages {a}-{b} of file {f.ord} as {read.get('status')}: "
                               f"{read.get('errors')}")
        parts.append(read.get("markdown") or "")
    text = without_images("\n".join(parts))
    artifacts.write(owner, artifacts.book_dir(book_id), STAGE, "title_pages.md", text, key,
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


# a translation's own ISBN is in its language's registration group; a foreign one beside it is the original's
def _own_isbn(found: SourceResult, languages: list[str]) -> None:
    isbns = [c for c in found.candidates if c.field in ("isbn", "original_isbn", "_other_isbn")]
    if not languages or len(isbns) < 2:
        return
    local = [c for c in isbns if _in_groups(c.value, languages[0])]
    if not local:
        return
    own = local[0].value
    has_original = any(c.field == "original_isbn" and c.value != own for c in isbns)
    for c in isbns:
        if c.value == own:
            c.field, c.evidence = "isbn", c.evidence + f"; in the {languages[0]} registration group"
        elif c.field in ("isbn", "_other_isbn") and not has_original and not _in_groups(c.value, languages[0]):
            c.field, c.evidence = "original_isbn", c.evidence + "; a foreign ISBN beside the book's own"
            has_original = True
        elif c.field == "isbn":
            c.field = "_other_isbn"


# Amazon by ISBN-10: the book's own (English books) confirms it; a shop link's ISBN becomes the book's only
# when that page shows the same edition or year as the book
def _amazon_checks(found: SourceResult, own: str | None, language: str | None, edition: int | None,
                   year: int | None) -> list[SourceResult]:
    out = []
    links = [c.value for c in found.candidates if c.field == "_link_isbn"]
    own10 = own if own and len(own) == 10 else title_pages.isbn10_of(own) if own else None
    keys = ([own10] if own10 and language == "en" else []) + [k for k in links if k != own10]
    for key in list(dict.fromkeys(keys))[:2]:
        page = catalogues.amazon(key)
        seen = {c.field: c.value for c in page.candidates}
        if key in links and key != own10:
            same = ((edition and seen.get("edition") == str(edition))
                    or (not edition and year and seen.get("year") == year))
            if not same:
                page = SourceResult("catalogue:amazon", covers=page.covers,
                                    failed=f"the link in the book points at ISBN {key}: edition {seen.get('edition')}, "
                                           f"year {seen.get('year')}; the book is edition {edition}, year {year}")
                out.append(page)
                continue
            page.add("isbn", seen.get("_isbn13") or key, 0.6, f"Amazon page of the link ISBN {key}, same edition")
        out.append(page)
    return out


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


def gather(book_id: int, manual: SourceResult) -> tuple[list[SourceResult], str]:
    files = intake.files_of(book_id)
    title, body, scanned = _title_and_body(book_id)
    results = [manual]
    results.append(file_metadata.read([pdf.info(settings.DATA_DIR / f.file_path) for f in files],
                                      [f.file_name for f in files]))
    pages = SourceResult("intake", covers=("pages",))
    pages.add("pages", sum(f.pages for f in files), 1.0, "page count of the files")
    results.append(pages)
    lang = language.read(body)
    results.append(lang)
    results.append(title_pages.imprint(title))
    found = title_pages.read(title)
    _own_isbn(found, next((c.value for c in lang.candidates), []))
    results.append(found)
    own = next((c.value for c in found.candidates if c.field == "isbn"), None)
    for name, lookup in catalogues.LOOKUPS.items():
        if own:
            results.append(lookup(own))
        else:
            results.append(SourceResult(name, covers=catalogues.COVERS[name], failed="no ISBN to look up"))
    results.append(model_reader.read(title))
    best_title = _best("title", results)
    book_language = next(iter(_best("languages", results) or []), None)
    edition, year = _best("edition", results), _best("year", results)
    edition = int(edition) if isinstance(edition, str) and edition.isdigit() else None
    results += _amazon_checks(found, own, book_language, edition, year)
    if not own and best_title and not _best("isbn", results):
        authors = _best("authors", results)
        results.append(catalogues.open_library_by_title(best_title, authors, book_language, edition, year))
        if book_language in ("ru", "uk", "be", "kk"):
            results.append(catalogues.labirint_by_title(best_title, authors))
            results.append(catalogues.bookvoed_by_title(best_title, authors))
    results.append(web.read(title, best_title, _best("authors", results), _best("isbn", results), book_language))
    results.append(_subject(best_title, title, body))
    _title_in_book_language(results, book_language)
    return results, script_of(body[:20000])


def _subject(title, title_text: str, body: str) -> SourceResult:
    try:
        return model_reader.subject(title, title_text[:4000] + body[:2000], title_text[-2000:])
    # a model that is away is waited for, not recorded as an empty subject
    except Deferred:
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


SCRIPTED = ("title", "authors", "translators", "illustrators", "publisher", "series")
ROMANISING = ("catalogue:open_library", "catalogue:open_library_title", "catalogue:google_books")


def script_of(text) -> str | None:
    text = " ".join(text) if isinstance(text, list) else str(text)
    counts: dict[str, int] = {}
    for c in text:
        if c.isalpha():
            name = unicodedata.name(c, "").split(" ")[0]
            counts[name] = counts.get(name, 0) + 1
    return max(counts, key=counts.get) if counts else None


def _pick(field: str, results: list[SourceResult], book_script: str | None = None) -> Candidate | None:
    candidates = [c for r in results for c in r.candidates if c.field == field]
    ranked = [c for source in _rank(field) for c in candidates if c.source == source]
    # a library romanises records ("Mir rasteniĭ"); only its values give way to the book's own script, while a
    # name really written in another script ("Leanpub" on a Russian book) stays
    if book_script and field in SCRIPTED and any(script_of(c.value) == book_script for c in ranked):
        ranked = [c for c in ranked if script_of(c.value) == book_script or c.source not in ROMANISING]
    return ranked[0] if ranked else None


def resolve(results: list[SourceResult], book_script: str | None = None) -> list[dict]:
    rows = []
    for field in FIELDS:
        pick = _pick(field, results, book_script)
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
    key = input_hash(book_id, manual)
    if previous is not None and previous.input_hash == key and not force:
        return previous.id
    results, book_script = gather(book_id, manual)
    rows = resolve(results, book_script)
    return write_version(book_id, key, rows, job_id, {"sources": [asdict(r) for r in results]})


# the book row is locked for the whole write, so two writers never take the same version number
def _lock_book(session, book_id: int) -> None:
    session.execute(select(Book.id).where(Book.id == book_id).with_for_update())


def _store_version(session, book_id: int, key: str, rows: list[dict], job_id: int | None) -> tuple[int, int]:
    number = (session.scalar(select(func.max(MetadataVersion.version))
                             .where(MetadataVersion.book_id == book_id)) or 0) + 1
    session.execute(update(MetadataVersion).where(MetadataVersion.book_id == book_id).values(current=False))
    version = MetadataVersion(book_id=book_id, version=number, input_hash=key, job_id=job_id, current=True)
    session.add(version)
    session.flush()
    for row in rows:
        session.add(MetadataField(metadata_version_id=version.id, **{k: v for k, v in row.items() if k != "optional"}))
    session.get(Book, book_id).stage = "metadata"
    return version.id, number


def _version_artifacts(book_id: int, version_id: int, number: int, key: str, rows: list[dict], evidence: dict) -> None:
    owner = artifacts.Owner(metadata_version_id=version_id)
    base = artifacts.version_dir(book_id, "metadata", number)
    artifacts.write(owner, base, STAGE, "sources.json", json.loads(json.dumps(evidence, default=str)), key)
    artifacts.write(owner, base, STAGE, "fields.json", rows, key)


def write_version(book_id: int, key: str, rows: list[dict], job_id: int | None, evidence: dict) -> int:
    with Session() as session:
        _lock_book(session, book_id)
        version_id, number = _store_version(session, book_id, key, rows, job_id)
        session.commit()
    _version_artifacts(book_id, version_id, number, key, rows, evidence)
    return version_id


# a hand-set value: read and written under one lock, and stamped so that the next collection runs again
MANUAL_STAMP = "manual-edit:"


def set_manual(book_id: int, name: str, value) -> int:
    with Session() as session:
        _lock_book(session, book_id)
        current = session.scalar(select(MetadataVersion).where(MetadataVersion.book_id == book_id,
                                                               MetadataVersion.current))
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
        key = MANUAL_STAMP + current.input_hash
        version_id, number = _store_version(session, book_id, key, rows, None)
        session.commit()
    _version_artifacts(book_id, version_id, number, key, rows, {"manual": {name: value}})
    return version_id
