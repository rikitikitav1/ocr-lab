# a run's bundle: the book's Markdown, its images, profile.yaml, report.json and report.md
import json
import re
from pathlib import Path

import artifacts
import profiles
import settings
import yaml
from assembly import referee
from document.model import PageMarker
from document.model import Piece as Model
from engines import ocr_languages
from knobs import registry
from orm.catalogue import Artifact, BookFile, LayoutVersion, Piece, Profile, Run, StructureNode
from orm.db import Session
from quality import book as book_quality
from quality import piece as piece_quality
from sqlalchemy import select
from writers import markdown

from stages import assemble, intake, result_run, run_pieces, run_state
from stages.metadata import fields as metadata_fields
from stages.structure import evidence


def _slug(text: str) -> str:
    return re.sub(r"[^\w]+", "-", text.lower()).strip("-")[:80] or "book"


def _piece_text(session, run_id: int, ord: int) -> tuple[str, str | None]:
    kept = _newest(session, run_id, ord, "piece.md")
    if kept is None:
        return f"<!-- node ord={ord} missing -->", None
    return artifacts.read(kept).decode(), kept.sha256


def _newest(session, run_id: int, ord: int, name: str) -> Artifact | None:
    return session.scalar(select(Artifact).where(Artifact.run_id == run_id, Artifact.name == name,
                                                 Artifact.piece_ord == ord, Artifact.removed_at.is_(None))
                          .order_by(Artifact.id.desc()).limit(1))


# the pictures written with the piece's newest text, by their name in the bundle
def _piece_images(session, run_id: int, ord: int) -> dict[str, Artifact]:
    text = _newest(session, run_id, ord, "piece.md")
    if text is None:
        return {}
    rows = session.scalars(select(Artifact).where(Artifact.run_id == run_id, Artifact.piece_ord == ord,
                                                  Artifact.input_hash == text.input_hash,
                                                  Artifact.name.startswith("images/")).order_by(Artifact.id))
    return {row.name: row for row in rows}


IMAGE_LINK = re.compile(r"!\[[^\]]*\]\((images/[^)\s]+)\)")


def _image_counts(document: str, images: dict) -> dict:
    links = IMAGE_LINK.findall(document)
    return {"files": len(images), "links": len(links), "broken_links": len(set(links) - set(images)),
            "unreferenced_files": len(set(images) - set(links))}


# which code and engine builds made which pieces: more than one entry means reruns mixed versions in the bundle
def _made_by(pieces: list) -> list[dict]:
    groups: dict[str, dict] = {}
    for c in pieces:
        made = (c.checks or {}).get("made_by")
        if made is not None:
            groups.setdefault(json.dumps(made, sort_keys=True), {**made, "pieces": []})["pieces"].append(c.ord)
    return list(groups.values())


# a piece's pages per file, in that file's own numbering, so a split book can be found
def _file_pages(files: list[BookFile], row: dict) -> list[dict]:
    if row.get("first_page") is None or row.get("last_page") is None:
        return []
    return [{"file": f.ord, "pages": [a, b]} for f, a, b in assemble.file_ranges(files, row["first_page"],
                                                                                  row["last_page"])]


# where the structure came from: the source that gave its base and the sources whose votes its entries carry
def _structure_sources(session, structure_version_id: int) -> dict:
    votes = session.scalars(select(StructureNode.votes)
                            .where(StructureNode.structure_version_id == structure_version_id))
    return {"base": evidence.base(session, structure_version_id),
            "voting": sorted({source for v in votes for source in (v or {})})}


def _piece_entry(c: Piece, row: dict, role: str | None, files: list[BookFile]) -> dict:
    return {"ord": c.ord, "title": row.get("title"), "role": role,
            "pages": f"{row.get('first_page')}-{row.get('last_page')}", "files": _file_pages(files, row),
            "status": c.status, "errors": c.errors, "checks": c.checks}


# report.json, every key of it made here
def _report(session, run: Run, book: dict, files: list[BookFile], rows: dict, pieces: list, numbers: dict,
            images: dict, doubled: list, fields: dict, profile: Profile | None) -> dict:
    cut = run_pieces.cut(session, run)
    roles = {c["ord"]: c["role"] for c in run_pieces.pieces(session, run)}
    return {"schema": 3, "book": book,
            "run": {"id": run.id, "dir": run.dir, "code_hash": run.code_hash, "engine_builds": run.engine_builds,
                    "made_by": _made_by(pieces)},
            "metadata": {"metadata_version": run.metadata_version_id, "structure_version": run.structure_version_id,
                         "structure_sources": _structure_sources(session, run.structure_version_id), "fields": fields},
            "numbers": {**numbers, "nodes": len(rows),
                        "pages_cut": {why: sorted(pages) for why, pages in cut.items()}},
            "images": images, "duplicates": doubled, "languages": _languages(run),
            "seconds": _seconds(session, run.id, pieces, book["pages"]),
            "profile_search": profiles.SEARCH_SKIPPED, "profile": profile_view(profile),
            "scans": _scans(session, run, pieces, files, assemble.languages_in(run.metadata_version_id)),
            "layer_spacing": [_spacing(f, pieces) for f in files], "monospace": _monospace(run, profile),
            "pieces": [_piece_entry(c, rows.get(c.ord, {}), roles.get(c.ord), files) for c in pieces]}


# per file, the letter and word gaps and whether spaced rows were joined, as the pieces' assemblies read them
def _spacing(f: BookFile, pieces: list) -> dict:
    seen = [((c.checks or {}).get("spacing") or {}).get(str(f.ord)) for c in pieces]
    kept = next((s for s in seen if s), None) or {"letters_p90": None, "words_p10": None, "joined": None}
    return {"file": f.ord, **kept}


# the monospace share of the page layout the run started on, and the preset of the run's own profile
def _monospace(run: Run, profile: Profile | None) -> dict:
    unmeasured = {"share": None, "pages": 0, "sampled": 0, "faces": []}
    with Session() as session:
        layout = session.get(LayoutVersion, run.layout_version_id) if run.layout_version_id is not None else None
    measured = (layout.layout if layout else {}).get("monospace") or unmeasured
    return {**measured, "preset": profile.preset if profile is not None else None}


# recognised pages in runs of one engine: book and file pages, the engines' agreement, words a dictionary knows
def _scans(session, run: Run, pieces: list, files: list[BookFile], languages: list[str]) -> list[dict]:
    picked, words = {}, {}
    for c in pieces:
        kept_pages = _newest(session, run.id, c.ord, "pages.json")
        kept_model = _newest(session, run.id, c.ord, "model.json")
        recognised = {int(p): v for p, v in (json.loads(artifacts.read(kept_pages)) if kept_pages else {}).items()
                      if "agreement" in v}
        picked.update(recognised)
        if recognised and kept_model is not None:
            page = None
            for b in Model.model_validate(json.loads(artifacts.read(kept_model))).blocks:
                if isinstance(b, PageMarker):
                    page = b.book_page
                elif page in recognised:
                    words.setdefault(page, []).extend(piece_quality.dictionary_words(referee.block_text(b)))
    out: list[dict] = []
    for page in sorted(picked):
        last = out[-1] if out else None
        if last and last["pages"][1] == page - 1 and last["engine"] == picked[page]["picked"]:
            last["pages"][1] = page
        else:
            out.append({"pages": [page, page], "engine": picked[page]["picked"]})
    for scan in out:
        pages = range(scan["pages"][0], scan["pages"][1] + 1)
        shares = [picked[p]["agreement"] for p in pages if picked[p]["agreement"] is not None]
        found = [w for p in pages for w in words.get(p, [])]
        f = intake.file_of(files, scan["pages"][0])
        scan.update({"file": f.ord if f else None,
                     "file_pages": [scan["pages"][0] - f.first_page + 1, scan["pages"][1] - f.first_page + 1]
                     if f else None,
                     "agreement": round(sum(shares) / len(shares), 3) if shares else None,
                     "agreement_min": min(shares) if shares else None, "dictionary_words": len(found),
                     "dictionary_share": piece_quality.dictionary_share(found, languages),
                     # neither engine gives a confidence of its own, so the range has none to report
                     "engine_confidence": None})
    return out


# what the book cost per phase: each reading's own time (kept with it, so a cached one still counts) and the assembly
def _seconds(session, run_id: int, pieces: list, pages: int) -> dict:
    ids = {i for c in pieces for i in run_state.round_readings(session, run_id, c.ord)[0].values()}
    rows = list(session.scalars(select(Artifact).where(Artifact.id.in_(ids)))) if ids else []
    # an engine with a reading kept before readings were timed has no honest total, so it reads unknown
    read = {e: None if any("seconds" not in (r.meta or {}) for r in rows if (r.meta or {}).get("engine") == e)
            else round(sum(r.meta["seconds"] for r in rows if (r.meta or {}).get("engine") == e), 1)
            for e in settings.ENGINES}
    assembly = round(sum(c.seconds or 0 for c in pieces), 1)
    total = None if None in read.values() else sum(read.values()) + assembly
    per_page = {**{f"read_{e}": None if v is None else round(v / pages, 2) for e, v in read.items()},
                "assemble": round(assembly / pages, 2),
                "total": None if total is None else round(total / pages, 2)} if pages else {}
    return {"read": read, "readings_untimed": sum("seconds" not in (r.meta or {}) for r in rows), "assemble": assembly,
            "pages": pages, "per_page": per_page}


# the knobs a run was made with; `applied` is what differs from the registry's defaults, per book and per piece
def profile_view(profile: Profile | None) -> dict | None:
    if profile is None:
        return None
    defaults = {path: spec["default"] for path, spec in registry.run_knobs().items()}
    differing = {path: v for path, v in profile.values.items() if v["value"] != defaults.get(path)}
    return {"id": profile.id, "preset": profile.preset, "sha256": profile.sha256,
            "knobs_applied": {path: v["value"] for path, v in differing.items()},
            "knob_sources": {path: v.get("source") for path, v in differing.items()},
            "piece_overrides": profile.piece_overrides}


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


# the worst-piece lists report.md shows, in its order: the key in numbers.worst, the heading, how a value reads
WORST = (("lost_text", "Most text lost", lambda c: _percent(c["lost_text"])),
         ("extra_text", "Most text not in the layer", lambda c: _percent(c["extra_text"])),
         ("out_of_order", "Most layer word runs out of order", lambda c: _percent(c["out_of_order"])),
         ("repeated_paragraphs", "Most paragraphs met twice in one piece", lambda c: c["repeated_paragraphs"]),
         ("long_headings", "Most long headings", lambda c: c["long_headings"]),
         ("max_heading_level", "Headings deeper than a piece's sub-sections",
          lambda c: f"level {c['max_heading_level']}"),
         ("agreement", "Least agreement on recognised pages", lambda c: c["agreement"]))
WORST_AFTER = (("subs_missing", "Most structure sub-nodes missing", lambda c: c["missing"]),)


def _worst(worst: dict, lists: tuple) -> list[str]:
    lines = []
    for key, label, shown in lists:
        if worst.get(key):
            lines += ["", f"## {label}", ""] + [f"- {c['ord']} {c['title']}: {shown(c)}" for c in worst[key]]
    return lines


# the short human summary: the book's numbers, then the worst pieces by each of them
def _profile_line(report: dict) -> str:
    profile = report.get("profile")
    if not profile:
        return "no profile"
    sources = profile.get("knob_sources") or {}
    knobs = ", ".join(f"{path} ({sources.get(path) or 'unknown'})" for path in sorted(profile["knobs_applied"]))
    return f"{knobs or 'none'} / {_listed(sorted(profile.get('piece_overrides') or {}, key=int))}"


def _summary(report: dict) -> str:
    n, i, langs = report["numbers"], report["images"], report["languages"]
    assembly = (report.get("seconds") or {}).get("per_page", {}).get("assemble")
    lines = [f"# {report['book']['title']}", "",
             "| | |", "|---|---|",
             f"| pieces | {n['pieces_done']} of {n['pieces']}, failed {_listed(n['pieces_failed'])} |",
             f"| text lost against the layer | {_percent(n['lost_text'])} on {n['layer_pages']} pages |",
             f"| text not in the layer | {_percent(n['extra_text'])} |",
             f"| layer words an engine set aside beyond the book's heads | {n.get('set_aside_words', 0)} |",
             f"| structure sub-nodes found as headings | {n['subs_found']} of {n['subs']} |",
             f"| long or empty headings | {n['long_headings']} / {n['empty_headings']} |",
             f"| headings by where their level came from | "
             f"{', '.join(f'{k} {v}' for k, v in sorted((n.get('heading_sources') or {}).items())) or 'none'} |",
             f"| deepest heading level / pieces below their own sections | {n.get('max_heading_level', 0)} / "
             f"{_listed(n.get('pieces_below_sections'))} |",
             f"| figures / not kept / image files / broken links | {i['figures']} / {n.get('figures_not_kept', 0)} / "
             f"{i['files']} / {i['broken_links']} |",
             f"| picture captions in the layer: as a caption / in a paragraph / as a heading / lost | "
             f"{n.get('captions', 0)}: {n.get('captions_in_caption', 0)} / {n.get('captions_in_paragraph', 0)} / "
             f"{n.get('captions_in_heading', 0)} / {n.get('captions_lost', 0)} |",
             f"| structure nodes whose headings stand out of order | {n.get('nodes_out_of_order', 0)} |",
             f"| paragraphs met in two pieces | {n['duplicates']} |",
             f"| paragraphs met twice in one piece | {n.get('repeated_paragraphs', 0)} |",
             f"| the book's running heads and folios left in the text / glued to a paragraph | "
             f"{n.get('running_heads_in_text', 0)} / {n.get('running_heads_glued', 0)} |",
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
             f"{_listed(n['pages_cut']['cover'])} |",
             f"| profile: knobs off the default (source) / pieces with their own knobs | {_profile_line(report)} |"]
    lines += _worst(n["worst"], WORST)
    fields = report["metadata"].get("fields") or {}
    if fields:
        lines += ["", "## Metadata", ""]
        lines += [f"- {name}: {_listed(f['value'])} ({f['source']}{', set by hand' if f['source'] == 'manual' else ''})"
                  for name, f in fields.items() if f["value"] not in (None, "", [])]
    service = [c for c in report["pieces"] if c["role"] == "service"]
    if service:
        lines += ["", "## Service pieces (before the first numbered piece and after the last; sub-nodes)", ""]
        lines += [f"- {c['ord']} {c['title']} {c['pages']}: {(c['checks'] or {}).get('subs', 0)}" for c in service]
    lines += _worst(n["worst"], WORST_AFTER)
    return "\n".join(lines) + "\n"


# every node of the structure with the unit that holds it and whether its heading was found there
def _structure(session, run: Run, pieces: list, rows: dict[int, dict]) -> list[dict]:
    held = {}
    for c in pieces:
        kept = _newest(session, run.id, c.ord, "model.json")
        for node in (json.loads(artifacts.read(kept)) if kept is not None else {}).get("nodes", []):
            held[node["ord"]] = (c.ord, node["pinned"], node.get("anchored", node["pinned"]))
    planned = run_pieces.pieces(session, run)

    # a node no piece holds goes with the piece a rerun of it would take, unpinned
    def unit(ord: int) -> int | None:
        if ord in held:
            return held[ord][0]
        piece = run_pieces.holding(planned, ord, rows[ord]["first_page"])
        return piece["ord"] if piece is not None else None

    return [{"ord": ord, "title": r["title"], "level": r["level"], "parent_ord": r.get("parent_ord"),
             "pages": [r["first_page"], r["last_page"]], "unit": unit(ord),
             "pinned": held.get(ord, (None, False))[1], "anchored": held.get(ord, (None, False, False))[2]}
            for ord, r in sorted(rows.items())]


# every block in exactly one node: blocks no node holds, and engine blocks two pieces both wrote (a page read twice)
def _ownership(session, run_id: int, pieces: list) -> dict:
    seen: dict[tuple, int] = {}
    counts = {"blocks_without_node": 0, "blocks_in_two": 0, "blocks_by_page": 0}
    for c in pieces:
        kept = _newest(session, run_id, c.ord, "model.json")
        page = None
        for b in (json.loads(artifacts.read(kept)) if kept is not None else {}).get("blocks", []):
            if b.get("type") == "page":
                page = b["book_page"]
                continue
            counts["blocks_without_node"] += b.get("parent_ord") is None
            counts["blocks_by_page"] += bool(b.get("by_page"))
            where = b.get("where")
            if where:
                key = (page, where["engine"], tuple(where["box"]))
                counts["blocks_in_two"] += key in seen and seen[key] != c.ord
                seen.setdefault(key, c.ord)
    return counts


# nodes and pinned nodes per level, the tree's own count of headings found
def _pins_by_level(nodes: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for n in nodes:
        level = out.setdefault(str(n["level"]), {"nodes": 0, "pinned": 0})
        level["nodes"] += 1
        level["pinned"] += n["pinned"]
    return out


# the bundle: the book title, the pieces in structure order, the images, report.json and report.md with the numbers
def write(run_id: int) -> dict:
    with Session() as session:
        run = session.get(Run, run_id)
        pieces = list(session.scalars(select(Piece).where(Piece.run_id == run_id).order_by(Piece.ord)))
        rows = {r["ord"]: r for r in run_pieces.rows(session, run.structure_version_id)}
        files = intake.files_of(run.book_id)
        stem = Path(files[0].file_name).stem if files else str(run.book_id)
        fields = metadata_fields.of_version(session, run.metadata_version_id)
        title = str((fields.get("title") or {}).get("value") or stem)
        book_id = run.book_id
        kept = {c.ord: _piece_text(session, run_id, c.ord) for c in pieces}
        texts = {ord: text for ord, (text, _) in kept.items()}
        images = {name: row for c in pieces for name, row in _piece_images(session, run_id, c.ord).items()}
        document = markdown.book(title, [texts[c.ord] for c in pieces])
        linked = _image_counts(document, images)
        doubled = book_quality.duplicates(texts)
        numbers = book_quality.numbers(
            [{"ord": c.ord, "title": rows.get(c.ord, {}).get("title"), "status": c.status, "checks": c.checks}
             for c in pieces], doubled)
        figures = sum((c.checks or {}).get("figures", 0) for c in pieces)
        structure = _structure(session, run, pieces, rows)
        numbers["nodes_by_level"] = _pins_by_level(structure)
        numbers.update(_ownership(session, run_id, pieces))
        numbers["reading_level"] = run.reading_level
        book = {"id": book_id, "sha256": [f.sha256 for f in files], "title": title,
                "pages": sum(f.pages for f in files)}
        profile = session.get(Profile, run.profile_id) if run.profile_id is not None else None
        report = _report(session, run, book, files, rows, pieces, numbers, {"figures": figures, **linked},
                         doubled, fields, profile)
    owner, base = artifacts.Owner(run_id=run_id), Path("bundles") / str(book_id) / str(run_id)
    # the bundle names its pieces' content, so a piece written again makes a new bundle
    builds = {engine: build for c in pieces for engine, build in
              ((c.checks or {}).get("made_by", {}).get("builds") or {}).items()}
    made_from = artifacts.Inputs({"stage": "bundle", "run": run_id,
                                  "pieces": {str(ord): sha for ord, (_, sha) in sorted(kept.items())},
                                  "images": {name: row.sha256 for name, row in sorted(images.items())},
                                  "profile": profile.sha256 if profile is not None else None,
                                  "builds": dict(sorted(builds.items()))})
    artifacts.write(owner, base, "bundle", f"{_slug(stem)}.md", document, made_from, folder="")
    # images/ is there even for a book without figures, so every bundle has the same layout
    artifacts.directory(base / "images")
    for name, row in images.items():
        artifacts.write(owner, base, "bundle", name, artifacts.read(row), made_from, folder="")
    artifacts.write(owner, base, "bundle", "structure.json", structure, made_from, folder="")
    artifacts.write(owner, base, "bundle", "report.json", report, made_from, folder="")
    if profile is not None:
        kept_profile = {"preset": profile.preset, "sha256": profile.sha256, "values": profile.values,
                        "piece_overrides": profile.piece_overrides}
        artifacts.write(owner, base, "bundle", "profile.yaml", yaml.safe_dump(kept_profile, sort_keys=True), made_from,
                        folder="")
    artifacts.write(owner, base, "bundle", "report.md", _summary(report), made_from, folder="")
    with Session() as session:
        run = session.get(Run, run_id)
        run_state.to_done(run, str(base))
        session.commit()
    best = result_run.recompute(book_id)
    return {"bundle": str(base), "pieces": len(pieces), "lost_text": numbers["lost_text"], "result_run": best}
