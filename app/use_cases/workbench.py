import artifacts
import job_queue
import job_specs
from knobs import registry
from mcp_tools import tool
from orm.catalogue import Artifact, Book, Run
from orm.db import Session


# the reading lands in the job's result by range key and artifact id, which the artifact door reads
@tool("read_range", "POST /v1/books/{id}/read_range",
      "Queue a GPU job that reads a book's page range with one engine and keeps the reading; returns the job id,"
      " whose result names the reading artifact. `force_raster_only` reads every page as a picture, as a scan is read"
      " (MinerU only); the result names the kept readings, contents_ocr.<file>.<a>-<b>.json beside a scan's"
      " contents readings.")
def read_range(id: int, engine: str, first_page: int, last_page: int, force_raster_only: bool = False) -> dict:
    options = job_specs.check("read_range", {"book_id": id, "engine": engine, "first_page": first_page,
                                             "last_page": last_page, "force_raster_only": force_raster_only})
    with Session() as session:
        book = session.get(Book, id)
        if book is None:
            raise LookupError(f"no book {id}")
        pages = book.pages or 0
    if not 1 <= first_page <= last_page <= pages:
        raise job_specs.Refused(f"pages {first_page}-{last_page} are not within book {id}'s 1-{pages}")
    return {"job_id": job_queue.enqueue("read_range", options, book_id=id)}


# before and after per piece land in the job's result and in data/scratch/reassemble; the run stays as it was
@tool("reassemble", "POST /v1/runs/{id}/reassemble",
      "Queue a CPU job that reassembles a finished run's pieces from their kept readings with the given knobs into a"
      " scratch result, leaving the run untouched; its result gives the piece numbers before and after, and today's"
      " code against what the run kept; empty knobs give only the latter. reading_level cuts the run at that tree"
      " level instead of its own (units_not_pieces names the run's units no piece matches), reread false leaves out"
      " the next piece's first page, as runs read before the re-read were cut; a piece whose pages the run did not"
      " read that way is not rebuilt and not_kept names the readings it lacks.")
def reassemble(id: int, knobs: dict, ords: list[int] | None = None, reading_level: int | None = None,
               reread: bool = True) -> dict:
    registry.check(knobs)
    options = job_specs.check("reassemble", {"run_id": id, "knobs": knobs, "ords": ords,
                                             "reading_level": reading_level, "reread": reread})
    with Session() as session:
        run = session.get(Run, id)
        if run is None:
            raise LookupError(f"no run {id}")
        book_id = run.book_id
    return {"job_id": job_queue.enqueue("reassemble", options, book_id=book_id)}


# any kept artifact by id, a book's readings included; a tool cannot carry bytes, so it gets the file as text
@tool("artifact", "GET /v1/artifacts/{id}",
      "Any artifact by id: its stage, name, path, owner, inputs and its file content as text, for a reading, a "
      "piece file or a pages.json.")
def get_artifact(id: int) -> dict:
    with Session() as session:
        row = session.get(Artifact, id)
        if row is None or row.removed_at is not None:
            raise LookupError(f"no artifact {id}")
    return {"id": row.id, "stage": row.stage, "name": row.name, "path": row.path, "book_id": row.book_id,
            "run_id": row.run_id, "piece": row.piece_ord, "meta": row.meta,
            "text": artifacts.read(row).decode(errors="replace")}

