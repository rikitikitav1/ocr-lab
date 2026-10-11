# book-level stages, chained: intake, then metadata, then the table of contents
import job_queue
from engines import card
from stages import intake
from stages.metadata import resolve
from stages.toc import collect
from use_cases import runs

from job_handlers import register


def _next_after_metadata(book_id: int, options: dict) -> None:
    if "toc" in options.get("what", []):
        job_queue.enqueue("toc", {"book_id": book_id, "what": ["toc"], "force": options["force"],
                                  "run": options.get("run", False)}, book_id=book_id)


# a submission that asked for a run gets it under the toc job, so waiting on the intake waits for the whole book
def _run_after_toc(options: dict, version_id: int) -> dict:
    out = {"toc_version_id": version_id}
    if options.get("run") and not job_queue.is_cancelled(options["_job_id"]):
        out["run_id"] = runs.start_run(options["book_id"], search=False)["run"]["id"]
    return out


@register("intake")
def run_intake(options: dict) -> dict:
    book_id = options["book_id"]
    probed = intake.probe(book_id)
    then = options["then"]
    run = "run" in then and "toc" in then
    # a cancel arriving while the files were read stops the chain here
    if not job_queue.is_cancelled(options["_job_id"]):
        if "metadata" in then:
            what = ["metadata", "toc"] if "toc" in then else ["metadata"]
            job_queue.enqueue("metadata", {"book_id": book_id, "what": what, "force": options["force"], "run": run},
                              book_id=book_id)
        elif "toc" in then:
            job_queue.enqueue("toc", {"book_id": book_id, "what": ["toc"], "force": options["force"], "run": run},
                              book_id=book_id)
    return {"pages": probed["text_layer"]["pages"], "without_layer": len(probed["text_layer"]["without_layer"]),
            "toc_sources": probed["toc_sources"]}


def _collect_metadata(options: dict) -> dict:
    book_id = options["book_id"]
    current = resolve.current_version(book_id)
    if "metadata" in options["what"] or current is None:
        version_id = resolve.collect(book_id, options["_job_id"], force=options["force"])
    else:
        version_id = current.id
    if not job_queue.is_cancelled(options["_job_id"]):
        _next_after_metadata(book_id, options)
    return {"metadata_version_id": version_id}


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


@register("toc")
def run_toc(options: dict) -> dict:
    book_id = options["book_id"]
    # a scan, or a text book whose text layer gave no contents, is read from the raster on the GPU lane
    def to_gpu(because: str) -> dict:
        handed = job_queue.enqueue("toc_scan", {"book_id": book_id, "what": ["toc"], "force": options["force"],
                                                "run": options.get("run", False)}, book_id=book_id)
        return {"toc_scan_job_id": handed, "because": because}

    if collect.wants_raster(book_id):
        return to_gpu("the contents are read from the raster")
    try:
        return _run_after_toc(options, collect.collect(book_id, options["_job_id"], force=options["force"]))
    except card.WrongLane as e:
        return to_gpu(str(e))


@register("toc_scan")
def run_toc_scan(options: dict) -> dict:
    return _run_after_toc(options, collect.collect(options["book_id"], options["_job_id"], force=options["force"],
                                                   raster=True))
