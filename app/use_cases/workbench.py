import artifacts
import job_queue
import job_specs
from knobs import registry
from mcp_tools import tool
from orm.catalogue import Artifact, Book, Run
from orm.db import Session
from orm.jobs import Job
from sqlalchemy import select


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
      " read that way is not rebuilt and not_kept names the readings it lacks. fresh makes the book-level lists"
      " (running heads, slots, notes, captions) anew instead of reading them back and gives their hashes in"
      " book_lists; each piece gives text_sha, the hash of its Markdown, so two code versions compare byte for byte.")
def reassemble(id: int, knobs: dict, ords: list[int] | None = None, reading_level: int | None = None,
               reread: bool = True, fresh: bool = False) -> dict:
    registry.check(knobs)
    options = job_specs.check("reassemble", {"run_id": id, "knobs": knobs, "ords": ords,
                                             "reading_level": reading_level, "reread": reread, "fresh": fresh})
    with Session() as session:
        run = session.get(Run, id)
        if run is None:
            raise LookupError(f"no run {id}")
        book_id = run.book_id
    return {"job_id": job_queue.enqueue("reassemble", options, book_id=book_id)}


# the gate lives on the stand, so a dropped caller loses nothing; its record is the next gate's base
@tool("reassembly_gate", "POST /v1/gates/reassembly",
      "Queue a CPU job that reassembles each named finished run fresh (as reassemble with fresh) with the given knobs"
      " and keeps the record of every piece's text and image hashes, counts and the book-level lists; with"
      " base_job_id it compares the record with that earlier gate's, and its result gives moved (books that moved)"
      " and a report per moved book; ignore names counts the change is meant to move. The reassemblies must run on"
      " one code, else the gate refuses; reload the workers before gating new code.")
def reassembly_gate(run_ids: list[int], knobs: dict | None = None, base_job_id: int | None = None,
                    ignore: list[str] | None = None) -> dict:
    knobs = knobs or {}
    registry.check(knobs)
    options = job_specs.check("reassembly_gate", {"run_ids": run_ids, "knobs": knobs, "base_job_id": base_job_id,
                                                  "ignore": ignore or []})
    with Session() as session:
        missing = sorted(set(run_ids) - set(session.scalars(select(Run.id).where(Run.id.in_(run_ids)))))
        base = session.get(Job, base_job_id) if base_job_id is not None else None
    if missing:
        raise LookupError(f"no runs {missing}")
    if base_job_id is not None and (base is None or base.type != "reassembly_gate" or base.status != "done"):
        raise job_specs.Refused(f"job {base_job_id} is no finished reassembly gate")
    return {"job_id": job_queue.enqueue("reassembly_gate", options)}


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

