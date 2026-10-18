# book-level stages, chained: intake, metadata, the page layout, the structure, the heading layout
import job_queue
import job_specs
import logging_setup
from engines import card
from stages import intake, run_start
from stages.layout import collect as layout
from stages.metadata import resolve
from stages.structure import collect

from job_handlers import register

log = logging_setup.get_logger(__name__)


def _next_after_metadata(book_id: int, options: dict) -> None:
    after = [w for w in options.get("what", []) if w in ("structure", "layout")]
    if after:
        job_queue.enqueue("layout_page", {"book_id": book_id, "what": after, "force": options["force"],
                                          "run": options.get("run", False)}, book_id=book_id)


# a submission that asked for a run gets it under the structure job, so waiting on the intake waits for the whole book
def _run_after_structure(options: dict, version_id: int) -> dict:
    out = {"structure_version_id": version_id, "runs_woken": job_queue.wake("book_run", options["book_id"])}
    # the heading layout is made again when the structure under it moved; it is forced only when layout is asked
    forced = options["force"] and "layout" in options.get("what", [])
    out["layout_headings_job_id"] = job_queue.enqueue("layout_headings", {"book_id": options["book_id"],
                                                                          "force": forced},
                                                      book_id=options["book_id"])
    if options.get("run") and not job_queue.is_cancelled(options["_job_id"]):
        out["run_id"] = run_start.start_one(options["book_id"])
    return out


@register("intake")
def run_intake(options: dict) -> dict:
    book_id = options["book_id"]
    probed = intake.probe(book_id)
    then = options["then"]
    run = "run" in then
    # a cancel arriving while the files were read stops the chain here
    if not job_queue.is_cancelled(options["_job_id"]):
        stages = [w for w in then if w != "run"]
        if stages:
            job_queue.enqueue(job_specs.chain_head(stages), {"book_id": book_id, "what": stages,
                                                             "force": options["force"], "run": run}, book_id=book_id)
    return {"pages": probed["text_layer"]["pages"], "without_layer": len(probed["text_layer"]["without_layer"]),
            "structure_sources": probed["structure_sources"]}


def _collect_metadata(options: dict) -> dict:
    book_id = options["book_id"]
    current = resolve.current_version(book_id)
    if "metadata" in options["what"] or current is None:
        version_id = resolve.collect(book_id, options["_job_id"], force=options["force"])
    else:
        version_id = current.id
    if not job_queue.is_cancelled(options["_job_id"]):
        _next_after_metadata(book_id, options)
    return {"metadata_version_id": version_id, "runs_woken": job_queue.wake("book_run", book_id)}


# a cached model answer or a text layer needs no card; a model call or a recognition that does goes to the GPU lane
@register("metadata")
def run_metadata(options: dict) -> dict:
    try:
        return _collect_metadata(options)
    except card.WrongLane as e:
        handed = job_queue.enqueue("metadata_gpu", {k: v for k, v in options.items() if not k.startswith("_")},
                                   book_id=options["book_id"])
        return {"metadata_gpu_job_id": handed, "because": str(e)}


@register("metadata_gpu")
def run_metadata_gpu(options: dict) -> dict:
    return _collect_metadata(options)


@register("structure")
def run_structure(options: dict) -> dict:
    book_id = options["book_id"]
    # a scan, or a text book whose text layer gave no contents, is read from the raster on the GPU lane
    def to_gpu(because: str) -> dict:
        handed = job_queue.enqueue("structure_scan", {"book_id": book_id, "what": options.get("what", ["structure"]),
                                                      "force": options["force"], "run": options.get("run", False)},
                                   book_id=book_id)
        return {"structure_scan_job_id": handed, "because": because}

    if collect.wants_raster(book_id):
        return to_gpu("the contents are read from the raster")
    try:
        return _run_after_structure(options, collect.collect(book_id, options["_job_id"], force=options["force"]))
    except card.WrongLane as e:
        return to_gpu(str(e))


@register("structure_scan")
def run_structure_scan(options: dict) -> dict:
    return _run_after_structure(options, collect.collect(options["book_id"], options["_job_id"], force=options["force"],
                                                   raster=True))


# runs read the page layout, so a failure is the job's like any other collection's, retried within its budget
@register("layout_page")
def run_layout_page(options: dict) -> dict:
    book_id = options["book_id"]
    out = {"layout_version_id": layout.collect_page(book_id, options["_job_id"],
                                                    force=options["force"] and "layout" in options["what"]),
           "runs_woken": job_queue.wake("book_run", book_id)}
    if job_queue.is_cancelled(options["_job_id"]):
        return out
    if "structure" in options["what"]:
        # the structure job carries layout on, so the heading layout after it is forced when asked
        asked = [w for w in options["what"] if w in ("structure", "layout")]
        out["structure_job_id"] = job_queue.enqueue("structure", {"book_id": book_id, "what": asked,
                                                      "force": options["force"], "run": options.get("run", False)},
                                              book_id=book_id)
    else:
        out["layout_headings_job_id"] = job_queue.enqueue("layout_headings", {
            "book_id": book_id, "force": options["force"] and "layout" in options["what"]}, book_id=book_id)
    return out


@register("layout_headings")
def run_layout_headings(options: dict) -> dict:
    version_id = layout.collect_headings(options["book_id"], options["_job_id"], force=options["force"])
    return {"layout_version_id": version_id} if version_id else {"skipped": "no structure yet"}
