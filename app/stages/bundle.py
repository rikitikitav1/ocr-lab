# a run's bundle: the book's Markdown, its images, profile.yaml, report.json and report.md
import json
import re
from pathlib import Path

import artifacts
import profiles
import settings
import yaml
from engines import ocr_languages
from knobs import registry
from orm.catalogue import Artifact, BookFile, Chapter, Profile, Run, TocEntry
from orm.db import Session
from quality import book as book_quality
from sqlalchemy import select
from writers import markdown

from stages import assemble, intake, result_run, run_chapters, run_state
from stages.metadata import fields as metadata_fields
from stages.toc import evidence


def _slug(text: str) -> str:
    return re.sub(r"[^\w]+", "-", text.lower()).strip("-")[:80] or "book"


def _chapter_text(session, run_id: int, ord: int) -> tuple[str, str | None]:
    kept = _newest(session, run_id, ord, "chapter.md")
    if kept is None:
        return f"<!-- chapter ord={ord} missing -->", None
    return artifacts.read(kept).decode(), kept.sha256


def _newest(session, run_id: int, ord: int, name: str) -> Artifact | None:
    return session.scalar(select(Artifact).where(Artifact.run_id == run_id, Artifact.name == name,
                                                 Artifact.chapter_ord == ord).order_by(Artifact.id.desc()).limit(1))


# the pictures written with the chapter's newest text, by their name in the bundle
def _chapter_images(session, run_id: int, ord: int) -> dict[str, Artifact]:
    text = _newest(session, run_id, ord, "chapter.md")
    if text is None:
        return {}
    rows = session.scalars(select(Artifact).where(Artifact.run_id == run_id, Artifact.chapter_ord == ord,
                                                  Artifact.input_hash == text.input_hash,
                                                  Artifact.name.startswith("images/")).order_by(Artifact.id))
    return {row.name: row for row in rows}


IMAGE_LINK = re.compile(r"!\[[^\]]*\]\((images/[^)\s]+)\)")


def _image_counts(document: str, images: dict) -> dict:
    links = IMAGE_LINK.findall(document)
    return {"files": len(images), "links": len(links), "broken_links": len(set(links) - set(images)),
            "unreferenced_files": len(set(images) - set(links))}


# which code and engine builds made which chapters: more than one entry means reruns mixed versions in the bundle
def _made_by(chapters: list) -> list[dict]:
    groups: dict[str, dict] = {}
    for c in chapters:
        made = (c.checks or {}).get("made_by")
        if made is not None:
            groups.setdefault(json.dumps(made, sort_keys=True), {**made, "chapters": []})["chapters"].append(c.ord)
    return list(groups.values())


# a chapter's pages per file, in that file's own numbering, so a split book can be found
def _file_pages(files: list[BookFile], row: dict) -> list[dict]:
    if row.get("first_page") is None or row.get("last_page") is None:
        return []
    return [{"file": f.ord, "pages": [a, b]} for f, a, b in assemble.file_ranges(files, row["first_page"],
                                                                                  row["last_page"])]


# where the toc came from: the source that gave its base and the sources whose votes its entries carry
def _toc_sources(session, toc_version_id: int) -> dict:
    votes = session.scalars(select(TocEntry.votes).where(TocEntry.toc_version_id == toc_version_id))
    return {"base": evidence.base(session, toc_version_id),
            "voting": sorted({source for v in votes for source in (v or {})})}


def _chapter_entry(c: Chapter, row: dict, role: str | None, files: list[BookFile]) -> dict:
    return {"ord": c.ord, "title": row.get("title"), "role": role,
            "pages": f"{row.get('first_page')}-{row.get('last_page')}", "files": _file_pages(files, row),
            "status": c.status, "errors": c.errors, "checks": c.checks}


# report.json, every key of it made here
def _report(session, run: Run, book: dict, files: list[BookFile], rows: dict, chapters: list, numbers: dict,
            images: dict, doubled: list, fields: dict, profile: Profile | None) -> dict:
    cut = run_chapters.cut(session, run)
    roles = {c["ord"]: c["role"] for c in run_chapters.chapters(session, run)}
    return {"schema": 2, "book": book,
            "run": {"id": run.id, "dir": run.dir, "code_hash": run.code_hash, "engine_builds": run.engine_builds,
                    "made_by": _made_by(chapters)},
            "metadata": {"metadata_version": run.metadata_version_id, "toc_version": run.toc_version_id,
                         "toc_sources": _toc_sources(session, run.toc_version_id), "fields": fields},
            "numbers": {**numbers, "toc_entries": len(rows),
                        "pages_cut": {why: sorted(pages) for why, pages in cut.items()}},
            "images": images, "duplicates": doubled, "languages": _languages(run),
            "seconds": _seconds(session, run.id, chapters, book["pages"]),
            "profile_search": profiles.SEARCH_SKIPPED, "profile": profile_view(profile),
            "chapters": [_chapter_entry(c, rows.get(c.ord, {}), roles.get(c.ord), files) for c in chapters]}


# what the book cost per phase: each reading's own time (kept with it, so a cached one still counts) and the assembly
def _seconds(session, run_id: int, chapters: list, pages: int) -> dict:
    ids = {i for c in chapters for i in run_state.round_readings(session, run_id, c.ord)[0].values()}
    rows = list(session.scalars(select(Artifact).where(Artifact.id.in_(ids)))) if ids else []
    # an engine with a reading kept before readings were timed has no honest total, so it reads unknown
    read = {e: None if any("seconds" not in (r.meta or {}) for r in rows if (r.meta or {}).get("engine") == e)
            else round(sum(r.meta["seconds"] for r in rows if (r.meta or {}).get("engine") == e), 1)
            for e in settings.ENGINES}
    assembly = round(sum(c.seconds or 0 for c in chapters), 1)
    total = None if None in read.values() else sum(read.values()) + assembly
    per_page = {**{f"read_{e}": None if v is None else round(v / pages, 2) for e, v in read.items()},
                "assemble": round(assembly / pages, 2),
                "total": None if total is None else round(total / pages, 2)} if pages else {}
    return {"read": read, "readings_untimed": sum("seconds" not in (r.meta or {}) for r in rows), "assemble": assembly,
            "pages": pages, "per_page": per_page}


# the knobs a run was made with; `applied` is what differs from the registry's defaults, per book and per chapter
def profile_view(profile: Profile | None) -> dict | None:
    if profile is None:
        return None
    defaults = {path: spec["default"] for path, spec in registry.run_knobs().items()}
    applied = {path: v["value"] for path, v in profile.values.items() if v["value"] != defaults.get(path)}
    return {"id": profile.id, "preset": profile.preset, "sha256": profile.sha256, "knobs_applied": applied,
            "chapter_overrides": profile.chapter_overrides}


# a book language without OCR data is read without it; the report names it so its data can be fetched
def _languages(run: Run) -> dict:
    book = assemble.languages_in(run.metadata_version_id)
    return {"book": book, "ocr": ocr_languages.tesseract_codes(book),
            "missing": [lang for lang in book if not ocr_languages.installed(lang)]}


def _percent(share: float | None) -> str:
    return "n/a" if share is None else f"{share * 100:.1f}%"


def _listed(value) -> str:
    if isinstance(value, (list, tuple)):
        return ", ".join(map(str, value)) or "none"
    return "none" if value in (None, "") else str(value)


def _reading_cost(report: dict) -> str:
    cost = report.get("seconds") or {}
    if not cost.get("per_page"):
        return "n/a"
    named = ", ".join(f"{e} {cost['per_page'].get('read_' + e) or 'unknown'}" for e in cost.get("read", {}))
    untimed = cost.get("readings_untimed") or 0
    return f"{named} ({untimed} readings kept before they were timed)" if untimed else named or "none"


# the worst-chapter lists report.md shows, in its order: the key in numbers.worst, the heading, how a value reads
WORST = (("lost_text", "Most text lost", lambda c: _percent(c["lost_text"])),
         ("extra_text", "Most text not in the layer", lambda c: _percent(c["extra_text"])),
         ("out_of_order", "Most layer word runs out of order", lambda c: _percent(c["out_of_order"])),
         ("repeated_paragraphs", "Most paragraphs met twice in one chapter", lambda c: c["repeated_paragraphs"]),
         ("long_headings", "Most long headings", lambda c: c["long_headings"]),
         ("max_heading_level", "Headings deeper than a chapter's sub-sections",
          lambda c: f"level {c['max_heading_level']}"),
         ("agreement", "Least agreement on recognised pages", lambda c: c["agreement"]))
WORST_AFTER = (("subs_missing", "Most toc sub-entries missing", lambda c: c["missing"]),)


def _worst(worst: dict, lists: tuple) -> list[str]:
    lines = []
    for key, label, shown in lists:
        if worst.get(key):
            lines += ["", f"## {label}", ""] + [f"- {c['ord']} {c['title']}: {shown(c)}" for c in worst[key]]
    return lines


# the short human summary: the book's numbers, then the worst chapters by each of them
def _summary(report: dict) -> str:
    n, i, langs = report["numbers"], report["images"], report["languages"]
    assembly = (report.get("seconds") or {}).get("per_page", {}).get("assemble")
    lines = [f"# {report['book']['title']}", "",
             "| | |", "|---|---|",
             f"| chapters | {n['chapters_done']} of {n['chapters']}, failed {_listed(n['chapters_failed'])} |",
             f"| text lost against the layer | {_percent(n['lost_text'])} on {n['layer_pages']} pages |",
             f"| text not in the layer | {_percent(n['extra_text'])} |",
             f"| layer words an engine set aside beyond the book's heads | {n.get('set_aside_words', 0)} |",
             f"| toc sub-entries found as headings | {n['subs_found']} of {n['subs']} |",
             f"| long or empty headings | {n['long_headings']} / {n['empty_headings']} |",
             f"| headings by where their level came from | "
             f"{', '.join(f'{k} {v}' for k, v in sorted((n.get('heading_sources') or {}).items())) or 'none'} |",
             f"| deepest heading level / chapters below their own sections | {n.get('max_heading_level', 0)} / "
             f"{_listed(n.get('chapters_below_sections'))} |",
             f"| figures / image files / broken links | {i['figures']} / {i['files']} / {i['broken_links']} |",
             f"| paragraphs met in two chapters | {n['duplicates']} |",
             f"| paragraphs met twice in one chapter | {n.get('repeated_paragraphs', 0)} |",
             f"| the book's running heads and folios left in the text | {n.get('running_heads_in_text', 0)} |",
             f"| layer word runs out of order | {_percent(n.get('out_of_order'))} |",
             f"| recognised pages, engines' word agreement, words a dictionary knows | {n['recognised_pages']}, "
             f"{'n/a' if n['agreement'] is None else n['agreement']}, {_percent(n.get('dictionary_share'))} |",
             f"| picture pages on recognised ranges | {n.get('picture_pages', 0)} |",
             f"| words from pages the layer check does not see | {n.get('layerless_words', 0)} |",
             f"| seconds per page: reading {_reading_cost(report)}, assembly "
             f"{'n/a' if assembly is None else assembly} |",
             f"| languages / OCR data / missing | {_listed(langs['book'])} / {_listed(langs['ocr'])} / "
             f"{_listed(langs['missing'])} |",
             f"| pages cut: printed contents / cover | {_listed(n['pages_cut']['contents'])} / "
             f"{_listed(n['pages_cut']['cover'])} |"]
    lines += _worst(n["worst"], WORST)
    fields = report["metadata"].get("fields") or {}
    if fields:
        lines += ["", "## Metadata", ""]
        lines += [f"- {name}: {_listed(f['value'])} ({f['source']}{', set by hand' if f['source'] == 'manual' else ''})"
                  for name, f in fields.items() if f["value"] not in (None, "", [])]
    service = [c for c in report["chapters"] if c["role"] == "service"]
    if service:
        lines += ["", "## Service chapters (before the first numbered chapter and after the last; sub-entries)", ""]
        lines += [f"- {c['ord']} {c['title']} {c['pages']}: {(c['checks'] or {}).get('subs', 0)}" for c in service]
    lines += _worst(n["worst"], WORST_AFTER)
    return "\n".join(lines) + "\n"


# the bundle: the book title, the chapters in toc order, the images, report.json and report.md with the numbers
def write(run_id: int) -> dict:
    with Session() as session:
        run = session.get(Run, run_id)
        chapters = list(session.scalars(select(Chapter).where(Chapter.run_id == run_id).order_by(Chapter.ord)))
        rows = {r["ord"]: r for r in run_chapters.rows(session, run.toc_version_id)}
        files = intake.files_of(run.book_id)
        stem = Path(files[0].file_name).stem if files else str(run.book_id)
        fields = metadata_fields.of_version(session, run.metadata_version_id)
        title = str((fields.get("title") or {}).get("value") or stem)
        book_id = run.book_id
        kept = {c.ord: _chapter_text(session, run_id, c.ord) for c in chapters}
        texts = {ord: text for ord, (text, _) in kept.items()}
        images = {name: row for c in chapters for name, row in _chapter_images(session, run_id, c.ord).items()}
        document = markdown.book(title, [texts[c.ord] for c in chapters])
        linked = _image_counts(document, images)
        doubled = book_quality.duplicates(texts)
        numbers = book_quality.numbers(
            [{"ord": c.ord, "title": rows.get(c.ord, {}).get("title"), "status": c.status, "checks": c.checks}
             for c in chapters], doubled)
        figures = sum((c.checks or {}).get("figures", 0) for c in chapters)
        book = {"id": book_id, "sha256": [f.sha256 for f in files], "title": title,
                "pages": sum(f.pages for f in files)}
        profile = session.get(Profile, run.profile_id) if run.profile_id is not None else None
        report = _report(session, run, book, files, rows, chapters, numbers, {"figures": figures, **linked},
                         doubled, fields, profile)
    owner, base = artifacts.Owner(run_id=run_id), Path("bundles") / str(book_id) / str(run_id)
    # the bundle names its chapters' content, so a chapter written again makes a new bundle
    made_from = artifacts.Inputs({"stage": "bundle", "run": run_id,
                                  "chapters": {str(ord): sha for ord, (_, sha) in sorted(kept.items())},
                                  "images": {name: row.sha256 for name, row in sorted(images.items())}})
    artifacts.write(owner, base, "", f"{_slug(stem)}.md", document, made_from)
    # images/ is there even for a book without figures, so every bundle has the same layout
    artifacts.directory(base / "images")
    for name, row in images.items():
        artifacts.write(owner, base, "", name, artifacts.read(row), made_from)
    artifacts.write(owner, base, "", "report.json", report, made_from)
    if profile is not None:
        artifacts.write(owner, base, "", "profile.yaml",
                        yaml.safe_dump({"preset": profile.preset, "sha256": profile.sha256, "values": profile.values,
                                        "chapter_overrides": profile.chapter_overrides}, sort_keys=True), made_from)
    artifacts.write(owner, base, "", "report.md", _summary(report), made_from)
    with Session() as session:
        run = session.get(Run, run_id)
        run_state.to_done(run, str(base))
        session.commit()
    best = result_run.recompute(book_id)
    return {"bundle": str(base), "chapters": len(chapters), "lost_text": numbers["lost_text"], "result_run": best}
