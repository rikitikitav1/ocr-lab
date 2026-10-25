# jobs that look at a book or a run without changing it: a page range read through one engine, a scratch reassembly

import hashlib

import artifacts
import settings
from knobs import registry
from orm.catalogue import Artifact, Piece, Run
from orm.db import Session
from sqlalchemy import select
from stages import assemble, run_pieces, run_state
from stages.piece_assembly import assembled
from stages.structure import scan
from writers import markdown as markdown_writer

from job_handlers import register


@register("read_range")
def read_range(options: dict) -> dict:
    if options.get("force_raster_only"):
        book_pages = list(range(options["first_page"], options["last_page"] + 1))
        pages = scan.recognise(options["book_id"], book_pages)
        return {"engine": "mineru", "force_raster_only": True, "pages_read": len(pages),
                "readings": scan.kept_names(options["book_id"], book_pages)}
    readings = assemble.read(options["book_id"], options["engine"], options["first_page"], options["last_page"])
    return {"engine": options["engine"], "readings": readings, "build": assemble.builds()[options["engine"]]}


# the piece's checks and pass counts in one flat row, so before and after compare key by key
def _numbers(checks: dict, counts: dict) -> dict:
    return {**checks, **{f"passes.{k}": v for k, v in counts.items()}}


DIFF_LINES = 3
# the writer's anchors are left out when a kept text is compared with today's
def _lines(markdown: str) -> list[str]:
    return markdown_writer.ANCHOR.sub("", markdown).split("\n")


# today's code against what the run kept: numbers that differ, and the text apart from heading marks and anchors
def _against_kept(run_id: int, ord: int, markdown: str, checks: dict) -> dict:
    with Session() as session:
        stored = (session.get(Piece, (run_id, ord)).checks or {})
        kept = session.scalar(select(Artifact).where(Artifact.run_id == run_id, Artifact.piece_ord == ord,
                                                     Artifact.name == "piece.md", Artifact.removed_at.is_(None))
                              .order_by(Artifact.id.desc()))
    old = _lines(artifacts.read(kept).decode()) if kept is not None else []
    new = _lines(markdown)
    bare = [line.lstrip("#").strip() for line in old] == [line.lstrip("#").strip() for line in new]
    moved = sum(a != b for a, b in zip(old, new, strict=False)) if bare else None
    numbers = sorted(k for k in checks if k not in ("made_by", "passes") and stored.get(k) != checks.get(k))
    # the first lines that differ, so a moved text can be read without assembling it again
    first = [[i, a, b] for i, (a, b) in enumerate(zip(old, new, strict=False)) if a != b][:DIFF_LINES]
    return {"numbers_changed": numbers, "text_changed": not bare, "headings_moved": moved, "lines": first,
            "line_counts": [len(old), len(new)]}


# the text names the images only, so a crop moved by a box is told by the bytes
def _images_sha(images: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    for name, png in sorted(images.items()):
        digest.update(name.encode() + b"\0" + png)
    return digest.hexdigest()[:16]


def _piece(run_id: int, ord: int, overrides: dict, level: int | None, reread: bool) -> dict:
    got, checks, _ = assembled(run_id, ord, None, level, reread)
    kept = _against_kept(run_id, ord, got.markdown, checks)
    before = _numbers(checks, got.counts)
    if overrides:
        got, checks, _ = assembled(run_id, ord, overrides, level, reread)
    after = _numbers(checks, got.counts)
    changed = sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))
    return {"ord": ord, "changed": changed, "before": before, "after": after, "against_kept": kept,
            "text_sha": hashlib.sha256(got.markdown.encode()).hexdigest()[:16], "images_sha": _images_sha(got.images)}


# a piece cut at another level or without the re-read page has other page ranges than the run read
def _unread(run_id: int, ord: int, level: int | None, reread: bool) -> list[str]:
    with Session() as session:
        run = session.get(Run, run_id)
        entry = run_pieces.piece_entry(session, run, ord, level, reread)
        readings = run_state.round_readings(session, run_id, ord)[0]
        cut = run_pieces.all_cut(session, run)
        book_id = run.book_id
    # a run read before the tail page went to the next piece read the whole range, and that reading serves too
    missing = [[assemble.reading_key(engine, f, a, b, regime) for engine in assemble.ENGINES
                for f, a, b, regime in assemble.ranges(book_id, first, last, cut)
                if assemble.reading_key(engine, f, a, b, regime) not in readings]
               for first, last in (assemble.read_pages(entry), (entry["first_page"], entry["last_page"]))]
    return min(missing, key=len)


# both sides are assembled by today's code, so only the knobs differ; nothing of the run is written
@register("reassemble")
def reassemble(options: dict) -> dict:
    run_id = options["run_id"]
    overrides = {path.removeprefix(registry.RUN_PREFIX): v for path, v in options["knobs"].items()}
    level, reread = options["reading_level"], options["reread"]
    with Session() as session:
        done = list(session.scalars(select(Piece.ord).where(Piece.run_id == run_id, Piece.status == "done")
                                    .order_by(Piece.ord)))
        # at another level the pieces may differ from the run's units: only pieces the run kept can be rebuilt
        pieces = [c["ord"] for c in run_pieces.pieces(session, session.get(Run, run_id), level, reread)]
    wanted = options["ords"] if options["ords"] is not None else (pieces if level is not None else done)
    unread = {ord: missing for ord in wanted if ord in done if (missing := _unread(run_id, ord, level, reread))}
    fresh = assemble.FRESH.set({} if options["fresh"] else None)
    try:
        rebuilt = [_piece(run_id, ord, overrides, level, reread) for ord in wanted if ord in done and ord not in unread]
        lists = {k: v for k, v in (assemble.FRESH.get() or {}).items() if isinstance(k, str)}
    finally:
        assemble.FRESH.reset(fresh)
    out = {"run_id": run_id, "knobs": options["knobs"], "reading_level": level, "reread": reread,
           "units_not_pieces": [o for o in done if o not in pieces] if level is not None else [],
           "skipped": [o for o in wanted if o not in done],
           "not_kept": {str(ord): missing for ord, missing in unread.items()},
           "pieces": rebuilt, "pieces_changed": [c["ord"] for c in rebuilt if c["changed"]],
           "kept_text_changed": [c["ord"] for c in rebuilt if c["against_kept"]["text_changed"]],
           "kept_numbers_changed": [c["ord"] for c in rebuilt if c["against_kept"]["numbers_changed"]],
           "kept_headings_moved": sum(c["against_kept"]["headings_moved"] or 0 for c in rebuilt),
           "book_lists": lists}
    artifacts.atomic_write(settings.DATA_DIR / "scratch" / "reassemble" / f"job-{options['_job_id']}.json", out)
    return out
