# a book run: chapters read engine by engine on the GPU lane, assembled on the CPU lane, then metrics and the bundle
import hashlib
import json
import time

import artifacts
import code_version
import job_queue
import profiles
from assembly import passes
from orm.catalogue import Chapter, Profile, Run, RunStatus
from orm.db import Session
from orm.jobs import Job
from quality import chapter as chapter_quality
from sqlalchemy import select
from stages import assemble, bundle, run_chapters, run_state
from stages.metadata import resolve
from stages.toc import collect

from job_handlers import Deferred, Final, register

ENGINES = assemble.ENGINES


COLLECTS = ("metadata", "metadata_gpu", "toc", "toc_scan")


# a collect of the book that failed for good while the run waited would fail again if queued anew
def _failed_collect(session, run: Run) -> Job | None:
    return session.scalars(select(Job).where(Job.book_id == run.book_id, Job.type.in_(COLLECTS),
                                             Job.status == "error", Job.created_at >= run.created_at)
                           .order_by(Job.id.desc())).first()


# a run works on today's metadata and toc: a stale version is collected again first and the run waits for it
def _fresh_versions(session, run: Run) -> None:
    stale = [what for what, check in (("metadata", resolve.stale), ("toc", collect.stale)) if check(run.book_id)]
    if stale:
        open_jobs = [i for kind in COLLECTS for i in job_queue.live_ids(type=kind)]
        mine = session.scalars(select(Job.id).where(Job.id.in_(open_jobs), Job.book_id == run.book_id)).all()
        if not mine:
            if (failed := _failed_collect(session, run)) is not None:
                raise Final(f"{failed.type} {failed.id} of book {run.book_id} failed for good: "
                            f"{(failed.error or {}).get('error')}")
            first = "metadata" if "metadata" in stale else "toc"
            job_queue.enqueue(first, {"book_id": run.book_id, "what": stale}, book_id=run.book_id)
        raise Deferred(f"waiting for fresh {', '.join(stale)} of book {run.book_id}", delay_seconds=30)
    run.toc_version_id = collect.current_version(run.book_id).id
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


# the run takes its toc version's chapters once and reads them engine-major, so the card changes hands twice a book
@register("book_run", ended=_run_ended)
def run_book(options: dict) -> dict:
    run_id = options["run_id"]
    builds = assemble.builds()
    with Session() as session:
        run = session.get(Run, run_id)
        if run is None:
            raise Final(f"no run {run_id}")
        if session.scalar(select(Chapter.ord).where(Chapter.run_id == run_id).limit(1)) is not None:
            return {"chapters": "already enqueued"}
        _fresh_versions(session, run)
        chapters = run_chapters.chapters(session, run)
        if not chapters:
            raise Final(f"toc version {run.toc_version_id} has no chapters")
        for c in chapters:
            session.add(Chapter(run_id=run_id, ord=c["ord"], toc_entry_id=c["id"]))
        run_state.start(run)
        run.code_hash, run.engine_builds = code_version.LOADED, builds
        for engine in ENGINES:
            for c in chapters:
                job_queue.enqueue("read_chapter", {"run_id": run_id, "ord": c["ord"], "engine": engine},
                                  run_id=run_id, book_id=run.book_id, session=session)
        session.commit()
    return {"chapters": len(chapters)}


def _read_ended(options: dict, outcome: str, error: str | None) -> None:
    run_id, ord = options["run_id"], options["ord"]
    if outcome == "error":
        run_state.fail(run_id, ord, f"{options['engine']} reading: {error}")
        run_state.finish(run_id)
        return
    run_state.assemble_when_read(run_id, ord)
    # a retried read whose other engine stays failed queues no assembly, so the chapter is settled here
    run_state.finish(run_id)


@register("read_chapter", ended=_read_ended)
def run_read(options: dict) -> dict:
    with Session() as session:
        run = session.get(Run, options["run_id"])
        entry = run_chapters.chapter_entry(session, run, options["ord"])
        book_id, cut = run.book_id, run_chapters.all_cut(session, run)
        languages = assemble.languages_in(run.metadata_version_id)
    readings = assemble.read(book_id, options["engine"], entry["first_page"], entry["last_page"], languages, cut)
    return {"ord": options["ord"], "engine": options["engine"], "ranges": len(readings), "readings": readings,
            "build": assemble.builds()[options["engine"]]}


def _chapter_ended(options: dict, outcome: str, error: str | None) -> None:
    if outcome == "error":
        run_state.fail(options["run_id"], options["ord"], error)
    run_state.finish(options["run_id"])


# what made the chapter: toc version, the profile's values, languages, the code, the builds that read it, the passes
def chapter_inputs(run: Run, profile: Profile | None, ord: int, knobs: dict, builds: dict,
                   languages: list[str]) -> artifacts.Inputs:
    return artifacts.Inputs({"stage": "assemble", "run": run.id, "ord": ord, "toc_version": run.toc_version_id,
                             "profile": profile.sha256 if profile is not None else None,
                             "languages": languages, "code": code_version.LOADED, "builds": builds,
                             "passes": hashlib.sha256(json.dumps(knobs, sort_keys=True).encode()).hexdigest()[:16]})


# a run without a profile (one started before profiles) assembles on the passes' config
def _knobs(profile: Profile | None, ord: int) -> dict:
    if profile is None:
        return dict(passes.conf())
    return profiles.passes_for(profile.values, profile.chapter_overrides, ord)


# a chapter put together from this round's kept readings; `overrides` go over the profile's passes and touch nothing
def assembled(run_id: int, ord: int, overrides: dict | None = None) -> tuple[assemble.Assembled, dict, dict]:
    with Session() as session:
        run = session.get(Run, run_id)
        entry = run_chapters.chapter_entry(session, run, ord)
        profile = session.get(Profile, run.profile_id) if run.profile_id is not None else None
        knobs = {**_knobs(profile, ord), **(overrides or {})}
        readings, builds = run_state.round_readings(session, run_id, ord)
        book_id, base = run.book_id, artifacts.run_dir(run.book_id, run_id)
        languages = assemble.languages_in(run.metadata_version_id)
        made_from = chapter_inputs(run, profile, ord, knobs, builds, languages)
        cut = run_chapters.all_cut(session, run)
    got = assemble.assemble(book_id, ord, entry["title"], entry["level"], entry["first_page"], entry["last_page"],
                            entry["subs"], languages, cut=cut, role=entry["role"], knobs=knobs, readings=readings,
                            shared_start=entry["shared_start"], next_title=entry["next_title"])
    shared = frozenset([entry["first_page"]] * entry["shared_start"] + [entry["last_page"]] * bool(entry["next_title"]))
    checks = chapter_quality.check(got.chapter, entry["subs"], got.layer, got.furniture, got.recognised, shared,
                                   languages)
    return got, checks, {"base": base, "made_from": made_from, "builds": builds, "languages": languages}


@register("assemble_chapter", ended=_chapter_ended)
def run_chapter(options: dict) -> dict:
    run_id, ord = options["run_id"], options["ord"]
    started = time.perf_counter()
    got, checks, made = assembled(run_id, ord)
    base, made_from, builds, languages = made["base"], made["made_from"], made["builds"], made["languages"]
    owner = artifacts.Owner(run_id=run_id)
    artifacts.write(owner, base, "assemble", "chapter.md", got.markdown, made_from, chapter_ord=ord)
    artifacts.write(owner, base, "assemble", "model.json", got.chapter.model_dump(), made_from, chapter_ord=ord)
    artifacts.write(owner, base, "assemble", "pages.json", got.pages, made_from, chapter_ord=ord)
    for name, png in got.images.items():
        artifacts.write(owner, base, "assemble", name, png, made_from, chapter_ord=ord)
    for ranged in got.steps:
        for name, blocks in ranged["steps"]:
            artifacts.write(owner, base, "assemble", f"model.{ranged['file']}.{ranged['pages'][0]}.{name}.json",
                            [b.model_dump() for b in blocks], made_from, chapter_ord=ord, heavy=True)
    with Session() as session:
        chapter = session.get(Chapter, (run_id, ord))
        chapter.status, chapter.engine = "done", "assembled"
        made_by = {"code": code_version.LOADED, "builds": builds, "languages": languages}
        chapter.checks = {**checks, "passes": got.counts, "made_by": made_by}
        chapter.seconds = round(time.perf_counter() - started, 2)
        session.commit()
    return {"ord": ord, "blocks": len(got.chapter.blocks), "lost_text": checks["lost_text"], "counts": got.counts}


def _metrics_ended(options: dict, outcome: str, error: str | None) -> None:
    if outcome == "error":
        run_state.metrics_failed(options["run_id"])


# the bundle once every chapter is done
@register("book_metrics", ended=_metrics_ended)
def run_metrics(options: dict) -> dict:
    return bundle.write(options["run_id"])
