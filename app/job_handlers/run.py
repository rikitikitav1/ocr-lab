# a book run: pieces read engine by engine on the GPU lane, assembled on the CPU lane, then metrics and the bundle
import hashlib
import json
import time

import artifacts
import code_version
import job_queue
import job_specs
import profiles
from assembly import passes
from orm.catalogue import Piece, Profile, Run, RunStatus
from orm.db import Session
from orm.jobs import Job
from quality import piece as piece_quality
from sqlalchemy import select
from stages import assemble, bundle, run_pieces, run_state
from stages.metadata import resolve
from stages.structure import collect

from job_handlers import Deferred, Final, register

ENGINES = assemble.ENGINES


COLLECTS = ("metadata", "metadata_gpu", "structure", "structure_scan")
# the page layout heads a structure collection and never fails the book, so it is waited on but not a failure
WAITED = (*COLLECTS, "layout_page")


# a collect of the book that failed for good while the run waited would fail again if queued anew
def _failed_collect(session, run: Run) -> Job | None:
    return session.scalars(select(Job).where(Job.book_id == run.book_id, Job.type.in_(COLLECTS),
                                             Job.status == "error", Job.created_at >= run.created_at)
                           .order_by(Job.id.desc())).first()


# a run works on today's metadata and structure: a stale version is collected again first and the run waits for it
def _fresh_versions(session, run: Run) -> None:
    stale = [what for what, check in (("metadata", resolve.stale), ("structure", collect.stale)) if check(run.book_id)]
    if stale:
        open_jobs = [i for kind in WAITED for i in job_queue.live_ids(type=kind)]
        mine = session.scalars(select(Job.id).where(Job.id.in_(open_jobs), Job.book_id == run.book_id)).all()
        if not mine:
            if (failed := _failed_collect(session, run)) is not None:
                raise Final(f"{failed.type} {failed.id} of book {run.book_id} failed for good: "
                            f"{(failed.error or {}).get('error')}")
            job_queue.enqueue(job_specs.chain_head(stale), {"book_id": run.book_id, "what": stale},
                              book_id=run.book_id)
        raise Deferred(f"waiting for fresh {', '.join(stale)} of book {run.book_id}", delay_seconds=30)
    run.structure_version_id = collect.current_version(run.book_id).id
    if (metadata := resolve.current_version(run.book_id)) is not None:
        run.metadata_version_id = metadata.id


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
    readings = assemble.read(book_id, options["engine"], *assemble.read_pages(entry), languages, cut)
    return {"ord": options["ord"], "engine": options["engine"], "ranges": len(readings), "readings": readings,
            "build": assemble.builds()[options["engine"]]}


def _piece_ended(options: dict, outcome: str, error: str | None) -> None:
    if outcome == "error":
        run_state.fail(options["run_id"], options["ord"], error)
    run_state.finish(options["run_id"])


# what made the piece: structure version, the profile's values, languages, the code, the builds that read it, the passes
def piece_inputs(run: Run, profile: Profile | None, ord: int, knobs: dict, builds: dict,
                   languages: list[str]) -> artifacts.Inputs:
    return artifacts.Inputs({"stage": "assemble", "run": run.id, "ord": ord,
                             "structure_version": run.structure_version_id,
                             "profile": profile.sha256 if profile is not None else None,
                             "languages": languages, "code": code_version.LOADED, "builds": builds,
                             "passes": hashlib.sha256(json.dumps(knobs, sort_keys=True).encode()).hexdigest()[:16],
                             # a run cut by parts and pieces keeps the inputs it always had
                             **({"reading_level": run.reading_level} if run.reading_level is not None else {})})


# a run without a profile (one started before profiles) assembles on the passes' config
def _knobs(profile: Profile | None, ord: int) -> dict:
    if profile is None:
        return dict(passes.conf())
    return profiles.passes_for(profile.values, profile.piece_overrides, ord)


# a piece meets its neighbours on its first and last pages; a run cut by parts and pieces cuts as it always did
def _boundaries(entry: dict) -> list[passes.Boundary] | None:
    if not entry.get("piece"):
        return None
    return [*([passes.Boundary(entry["first_page"], entry["title"], False)] if entry["shared_start"] else []),
            *([passes.Boundary(entry["last_page"], entry["next_title"], True)] if entry["next_title"] else [])]


# a re-read boundary page is the next piece's own; the tail the earlier piece took off it is that piece's alone
def measured_layer(entry: dict, layer: dict[int, str], boundaries: list[dict]) -> dict[int, str]:
    tails = {r["page"]: r.get("tail_text", "") for r in boundaries if r.get("read")}
    out = dict(layer)
    first, last = entry["first_page"], entry["last_page"]
    if entry.get("reread_end") and last in out:
        out[last] = tails.get(last, "")
    if entry.get("reread_start") and first in out and tails.get(first):
        rest = piece_quality.words(out[first]) - piece_quality.words(tails[first])
        out[first] = " ".join(rest.elements())
    return out


# a piece put together from this round's kept readings; `overrides` go over the profile's passes and touch nothing
def assembled(run_id: int, ord: int, overrides: dict | None = None, level: int | None = None,
              reread: bool = True) -> tuple[assemble.Assembled, dict, dict]:
    with Session() as session:
        run = session.get(Run, run_id)
        entry = run_pieces.piece_entry(session, run, ord, level, reread)
        profile = session.get(Profile, run.profile_id) if run.profile_id is not None else None
        knobs = {**_knobs(profile, ord), **(overrides or {})}
        readings, builds = run_state.round_readings(session, run_id, ord)
        # a piece takes its tail on the page the next one opens on from the next one's reading of it
        neighbour = run_state.round_readings(session, run_id, entry["next_ord"])[0] \
            if entry.get("piece") and entry.get("next_ord") is not None else None
        book_id, base = run.book_id, artifacts.run_dir(run.book_id, run_id)
        languages = assemble.languages_in(run.metadata_version_id)
        made_from = piece_inputs(run, profile, ord, knobs, builds, languages)
        cut = run_pieces.all_cut(session, run)
    got = assemble.assemble(book_id, ord, entry["title"], entry["level"], entry["first_page"], entry["last_page"],
                            entry["subs"], languages, cut=cut, role=entry["role"], knobs=knobs, readings=readings,
                            shared_start=entry["shared_start"], next_title=entry["next_title"],
                            nodes=entry["nodes"], piece=entry.get("piece", False),
                            reread_end=entry.get("reread_end", False), boundaries=_boundaries(entry),
                            neighbour=neighbour)
    reread_start, reread_end = entry.get("reread_start", False), entry.get("reread_end", False)
    shared = frozenset([entry["first_page"]] * (entry["shared_start"] and not reread_start)
                       + [entry["last_page"]] * (bool(entry["next_title"]) and not reread_end))
    layer = measured_layer(entry, got.layer, got.boundaries)
    recognised = {p: s for p, s in got.recognised.items() if not (reread_end and p == entry["last_page"])}
    checks = piece_quality.check(got.piece, entry["subs"], layer, got.furniture, recognised, shared, languages)
    return got, checks, {"base": base, "made_from": made_from, "builds": builds, "languages": languages}


@register("assemble_piece", ended=_piece_ended)
def run_piece(options: dict) -> dict:
    run_id, ord = options["run_id"], options["ord"]
    started = time.perf_counter()
    got, checks, made = assembled(run_id, ord)
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
        piece.checks = {**checks, "passes": got.counts, "made_by": made_by}
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
