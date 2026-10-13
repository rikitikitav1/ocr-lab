# jobs that look at a book or a run without changing it: a page range read through one engine, a scratch reassembly
import artifacts
import settings
from knobs import registry
from orm.catalogue import Chapter
from orm.db import Session
from sqlalchemy import select
from stages import assemble
from stages.toc import scan

from job_handlers import register
from job_handlers.run import assembled


@register("read_range")
def read_range(options: dict) -> dict:
    if options.get("force_raster_only"):
        book_pages = list(range(options["first_page"], options["last_page"] + 1))
        pages = scan.recognise(options["book_id"], book_pages)
        return {"engine": "mineru", "force_raster_only": True, "pages_read": len(pages),
                "readings": scan.kept_names(options["book_id"], book_pages)}
    readings = assemble.read(options["book_id"], options["engine"], options["first_page"], options["last_page"])
    return {"engine": options["engine"], "readings": readings, "build": assemble.builds()[options["engine"]]}


# the chapter's checks and pass counts in one flat row, so before and after compare key by key
def _numbers(checks: dict, counts: dict) -> dict:
    return {**checks, **{f"passes.{k}": v for k, v in counts.items()}}


def _chapter(run_id: int, ord: int, overrides: dict) -> dict:
    got, checks, _ = assembled(run_id, ord)
    before = _numbers(checks, got.counts)
    got, checks, _ = assembled(run_id, ord, overrides)
    after = _numbers(checks, got.counts)
    changed = sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))
    return {"ord": ord, "changed": changed, "before": before, "after": after}


# both sides are assembled by today's code, so only the knobs differ; nothing of the run is written
@register("reassemble")
def reassemble(options: dict) -> dict:
    run_id = options["run_id"]
    overrides = {path.removeprefix(registry.RUN_PREFIX): v for path, v in options["knobs"].items()}
    with Session() as session:
        done = list(session.scalars(select(Chapter.ord).where(Chapter.run_id == run_id, Chapter.status == "done")
                                    .order_by(Chapter.ord)))
    wanted = options["ords"] if options["ords"] is not None else done
    chapters = [_chapter(run_id, ord, overrides) for ord in wanted if ord in done]
    out = {"run_id": run_id, "knobs": options["knobs"], "skipped": [o for o in wanted if o not in done],
           "chapters": chapters, "chapters_changed": [c["ord"] for c in chapters if c["changed"]]}
    artifacts.atomic_write(settings.DATA_DIR / "scratch" / "reassemble" / f"job-{options['_job_id']}.json", out)
    return out
