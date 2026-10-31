# the structure evaluation as a job; the work itself lives in evaluation.structure_run
import job_queue
from evaluation import element_run, structure_run
from job_signals import Deferred, Final
from orm.db import Session
from orm.jobs import Job
from sqlalchemy import select

from job_handlers import register

# a set over the shelf's own books goes one child job a book; the HiPS set registers its books as it goes
ONE_BY_ONE = ("hips",)


@register("structure_eval_book")
def run_structure_eval_book(options: dict) -> dict:
    return structure_run.member(options["book_id"], options["set"])


@register("structure_eval")
def run_structure_eval(options: dict) -> dict:
    name, job_id = options["set"], options["_job_id"]
    if name in ONE_BY_ONE:
        return structure_run.run(name, options["book_ids"], job_id)
    with Session() as session:
        children = session.scalars(select(Job).where(Job.parent_id == job_id, Job.type == "structure_eval_book")
                                   .order_by(Job.book_id)).all()
    if not children:
        books = structure_run.books_of(name, options["book_ids"])
        for book_id in books:
            job_queue.enqueue("structure_eval_book", {"book_id": book_id, "set": name}, parent_id=job_id,
                              book_id=book_id)
        raise Deferred(f"waiting for {len(books)} books", delay_seconds=30)
    left = [c.id for c in children if c.status not in job_queue.FINISHED]
    if left:
        raise Deferred(f"waiting for {len(left)} of {len(children)} books", delay_seconds=30)
    if failed := [c.id for c in children if c.status != "done"]:
        raise Final(f"books not scored: {failed}")
    codes = sorted({c.code_hash for c in children})
    if len(codes) != 1:
        raise Final(f"the books were scored on several codes {codes}: reload the workers and evaluate again")
    return structure_run.summary_of(name, [c.result for c in children])


@register("element_eval")
def run_element_eval(options: dict) -> dict:
    return element_run.run(options["engines"], options["ids"], options["_job_id"], options["knobs"])
