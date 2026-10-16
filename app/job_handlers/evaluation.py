# the structure evaluation as a job; the work itself lives in evaluation.structure_run
from evaluation import element_run, structure_run

from job_handlers import register


@register("structure_eval")
def run_structure_eval(options: dict) -> dict:
    return structure_run.run(options["set"], options["book_ids"], options["_job_id"])


@register("element_eval")
def run_element_eval(options: dict) -> dict:
    return element_run.run(options["engines"], options["ids"], options["_job_id"], options["knobs"])
