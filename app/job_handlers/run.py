# a book run: pieces read engine by engine on the GPU lane, assembled on the CPU lane, then metrics and the bundle
import time

import artifacts
import code_version
import job_queue
import job_specs
import profiles
from orm.catalogue import Piece, Profile, Run, RunStatus
from orm.db import Session
from orm.jobs import Job
from sqlalchemy import select
from stages import assemble, bundle, piece_assembly, run_pieces, run_state
from stages.layout import collect as layout_collect
from stages.metadata import resolve
from stages.structure import collect

from job_handlers import Deferred, Final, register

ENGINES = assemble.ENGINES


COLLECTS = ("metadata", "metadata_gpu", "layout_page", "structure", "structure_scan")


# a collect of the book that failed for good while the run waited would fail again if queued anew
def _failed_collect(session, run: Run) -> Job | None:
    return session.scalars(select(Job).where(Job.book_id == run.book_id, Job.type.in_(COLLECTS),
                                             Job.status == "error", Job.created_at >= run.created_at)
                           .order_by(Job.id.desc())).first()


# a run works on today's metadata and structure: a stale version is collected again first and the run waits for it
def _fresh_versions(session, run: Run) -> None:
    stale = [what for what, check in (("metadata", resolve.stale), ("structure", collect.stale)) if check(run.book_id)]
    if stale:
        open_jobs = [i for kind in COLLECTS for i in job_queue.live_ids(type=kind)]
        mine = session.scalars(select(Job.id).where(Job.id.in_(open_jobs), Job.book_id == run.book_id)).all()
        if not mine:
            if (failed := _failed_collect(session, run)) is not None:
                raise Final(f"{failed.type} {failed.id} of book {run.book_id} failed for good: "
                            f"{(failed.error or {}).get('error')}")
            job_queue.enqueue(job_specs.chain_head(stale), {"book_id": run.book_id, "what": stale},
                              book_id=run.book_id)
        raise Deferred(f"waiting for fresh {', '.join(stale)} of book {run.book_id}", delay_seconds=30)
    # a page layout being collected for the book now is waited for, so the run pins that one and not a second
    collecting = session.scalars(select(Job.id).where(Job.id.in_(job_queue.live_ids(type="layout_page")),
                                                      Job.book_id == run.book_id)).first()
    if collecting is not None:
        raise Deferred(f"waiting for the page layout of book {run.book_id} (job {collecting})", delay_seconds=30)
    run.structure_version_id = collect.current_version(run.book_id).id
    if (metadata := resolve.current_version(run.book_id)) is not None:
        run.metadata_version_id = metadata.id
    run.layout_version_id = _page_layout(run.book_id)
    _preset_of_pinned_layout(session, run)


# a profile the stand chose (no parent: not derived, not set by hand) follows the preset the pinned layout chooses
def _preset_of_pinned_layout(session, run: Run) -> None:
    profile = session.get(Profile, run.profile_id) if run.profile_id is not None else None
    if profile is None or profile.parent_id is not None:
        return
    preset = profiles.chosen_preset(run.book_id)[0]
    if preset != profile.preset:
        run.profile_id = profiles.resolve(session, run.book_id, preset).id


# a run reads the page layout, so one missing or made from other inputs is collected here, on the CPU lane it needs
def _page_layout(book_id: int) -> int:
    kept = layout_collect.current(book_id, layout_collect.PAGE)
    if kept is not None and not layout_collect.stale(book_id, layout_collect.PAGE):
        return kept.id
    return layout_collect.collect_page(book_id)


# a run whose start failed for good, its wait for fresh versions included, stops in attention instead of queued
def _run_ended(options: dict, outcome: str, error: str | None) -> None:
    if outcome != "error":
        return
    with Session() as session:
        run = session.get(Run, options["run_id"])
        if run is not None and run.stage in (None, RunStatus.QUEUED):
            run_state.to_attention(run)
            session.commit()


# the run takes its structure version's pieces once and reads them engine-major, so the card changes hands twice a book
@register("book_run", ended=_run_ended)
def run_book(options: dict) -> dict:
    run_id = options["run_id"]
    builds = assemble.builds()
    with Session() as session:
        run = session.get(Run, run_id)
        if run is None:
            raise Final(f"no run {run_id}")
        if session.scalar(select(Piece.ord).where(Piece.run_id == run_id).limit(1)) is not None:
            return {"pieces": "already enqueued"}
        _fresh_versions(session, run)
        pieces = run_pieces.pieces(session, run)
        if not pieces:
            raise Final(f"structure version {run.structure_version_id} has no nodes")
        for c in pieces:
            session.add(Piece(run_id=run_id, ord=c["ord"], node_id=c["id"]))
        run_state.start(run)
        run.code_hash, run.engine_builds = code_version.LOADED, builds
        for engine in ENGINES:
            for c in pieces:
                job_queue.enqueue("read_piece", {"run_id": run_id, "ord": c["ord"], "engine": engine},
                                  run_id=run_id, book_id=run.book_id, session=session)
        session.commit()
    return {"pieces": len(pieces)}


def _read_ended(options: dict, outcome: str, error: str | None) -> None:
    run_id, ord = options["run_id"], options["ord"]
    if outcome == "error":
        run_state.fail(run_id, ord, f"{options['engine']} reading: {error}")
        run_state.finish(run_id)
        return
    run_state.assemble_when_read(run_id, ord)
    # a retried read whose other engine stays failed queues no assembly, so the piece is settled here
    run_state.finish(run_id)


@register("read_piece", ended=_read_ended)
def run_read(options: dict) -> dict:
    with Session() as session:
        run = session.get(Run, options["run_id"])
        entry = run_pieces.piece_entry(session, run, options["ord"])
        book_id, cut = run.book_id, run_pieces.all_cut(session, run)
        languages = assemble.languages_in(run.metadata_version_id)
    pages = assemble.read_pages(entry)
    kept = assemble.readings_kept(book_id, options["engine"], *pages, languages, cut)
    readings = assemble.read(book_id, options["engine"], *pages, languages, cut)
    return {"ord": options["ord"], "engine": options["engine"], "ranges": len(readings), "readings": readings,
            "build": assemble.builds()[options["engine"]], "kept": kept}


def _piece_ended(options: dict, outcome: str, error: str | None) -> None:
    if outcome == "error":
        run_state.fail(options["run_id"], options["ord"], error)
    run_state.finish(options["run_id"])


@register("assemble_piece", ended=_piece_ended)
def run_piece(options: dict) -> dict:
    run_id, ord = options["run_id"], options["ord"]
    started = time.perf_counter()
    got, checks, made = piece_assembly.assembled(run_id, ord)
    base, made_from, builds, languages = made["base"], made["made_from"], made["builds"], made["languages"]
    owner = artifacts.Owner(run_id=run_id)
    artifacts.write(owner, base, "assemble", "piece.md", got.markdown, made_from, piece_ord=ord)
    artifacts.write(owner, base, "assemble", "model.json", got.piece.model_dump(), made_from, piece_ord=ord)
    artifacts.write(owner, base, "assemble", "pages.json", got.pages, made_from, piece_ord=ord)
    if got.boundaries:
        artifacts.write(owner, base, "assemble", "boundaries.json", got.boundaries, made_from, piece_ord=ord)
    for name, png in got.images.items():
        artifacts.write(owner, base, "assemble", name, png, made_from, piece_ord=ord)
    for ranged in got.steps:
        for name, blocks in ranged["steps"]:
            artifacts.write(owner, base, "assemble", f"model.{ranged['file']}.{ranged['pages'][0]}.{name}.json",
                            [b.model_dump() for b in blocks], made_from, piece_ord=ord, heavy=True)
    with Session() as session:
        piece = session.get(Piece, (run_id, ord))
        piece.status, piece.engine = "done", "assembled"
        made_by = {"code": code_version.LOADED, "builds": builds, "languages": languages}
        piece.checks = {**checks, "passes": got.counts, "made_by": made_by, "spacing": got.spacing}
        piece.seconds = round(time.perf_counter() - started, 2)
        session.commit()
    return {"ord": ord, "blocks": len(got.piece.blocks), "lost_text": checks["lost_text"], "counts": got.counts}


def _metrics_ended(options: dict, outcome: str, error: str | None) -> None:
    if outcome == "error":
        run_state.metrics_failed(options["run_id"])


# the bundle once every piece is done
@register("book_metrics", ended=_metrics_ended)
def run_metrics(options: dict) -> dict:
    return bundle.write(options["run_id"])
