# book-level stages, chained: intake, then metadata, then the table of contents once that stage exists
import job_queue
import job_specs
from stages import intake
from stages.metadata import resolve

from job_handlers import register


def _next_after_metadata(book_id: int, options: dict) -> None:
    if "toc" in options.get("what", ["toc"]) and "toc" in job_specs.BUILT_BOOK_STAGES:
        job_queue.enqueue("toc", {"book_id": book_id}, book_id=book_id)


@register("intake")
def run_intake(options: dict) -> dict:
    book_id = options["book_id"]
    probed = intake.probe(book_id)
    # a cancel arriving while the files were read stops the chain here
    if not job_queue.is_cancelled(options["_job_id"]):
        job_queue.enqueue("metadata", {"book_id": book_id}, book_id=book_id)
    return {"pages": probed["text_layer"]["pages"], "without_layer": len(probed["text_layer"]["without_layer"]),
            "toc_sources": probed["toc_sources"]}


@register("metadata")
def run_metadata(options: dict) -> dict:
    book_id = options["book_id"]
    current = resolve.current_version(book_id)
    if "metadata" in options["what"] or current is None:
        version_id = resolve.collect(book_id, options["_job_id"], force=options["force"])
    else:
        version_id = current.id
    if not job_queue.is_cancelled(options["_job_id"]):
        _next_after_metadata(book_id, options)
    return {"metadata_version_id": version_id}
