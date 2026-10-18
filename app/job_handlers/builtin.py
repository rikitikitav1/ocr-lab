from stages import cleanup

from job_handlers import register


# smoke jobs for the stand door and the tests: one per lane
@register("noop")
def noop(options: dict) -> dict:
    return {"ok": True}


@register("noop_gpu")
def noop_gpu(options: dict) -> dict:
    return {"ok": True}


# the cleanup as a job, for a caller that queues it beside other work
@register("cleanup")
def run_cleanup(options: dict) -> dict:
    return cleanup.cleanup(options.get("dry_run", True))


# a batch is written done by its door; a handler exists so job_types shows it as built
@register("batch")
def run_batch(options: dict) -> dict:
    return {"door": options["door"]}
