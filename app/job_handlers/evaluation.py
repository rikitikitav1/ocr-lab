# the structure evaluation as a job; the work itself lives in evaluation.structure_run
import job_queue
from evaluation import element_run, structure_run
from job_signals import Final

from job_handlers import register


@register("structure_eval_book")
def run_structure_eval_book(options: dict) -> dict:
    return structure_run.member(options["book_id"], options["set"])


# a set over the shelf's own books goes one child job a book; the HiPS set registers its books as it goes
@register("structure_eval")
def run_structure_eval(options: dict) -> dict:
    name, job_id = options["set"], options["_job_id"]
    if name == "hips":
        return structure_run.run_hips(job_id)
    children = job_queue.wait_for_children(
        job_id, "structure_eval_book", lambda: [{"options": {"book_id": b, "set": name}, "book_id": b}
                                                for b in structure_run.books_of(name, options["book_ids"])])
    if failed := [c.id for c in children if c.status != "done"]:
        raise Final(f"books not scored: {failed}")
    if len(codes := sorted({c.code_hash for c in children})) > 1:
        raise Final(f"the books were scored on several codes {codes}: reload the workers and evaluate again")
    return structure_run.summary_of(name, sorted((c.result for c in children), key=lambda r: r["book_id"]))


@register("element_eval")
def run_element_eval(options: dict) -> dict:
    return element_run.run(options["engines"], options["ids"], options["_job_id"], options["knobs"])
