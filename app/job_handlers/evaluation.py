# the toc evaluation as a job; the work itself lives in evaluation.toc_run
from evaluation import element_run, toc_run

from job_handlers import register


@register("toc_eval")
def run_toc_eval(options: dict) -> dict:
    return toc_run.run(options["set"], options["book_ids"], options["_job_id"])


@register("element_eval")
def run_element_eval(options: dict) -> dict:
    return element_run.run(options["engines"], options["ids"], options["_job_id"], options["knobs"])
