from job_handlers import register


# smoke jobs for the stand door and the tests: one per lane
@register("noop")
def noop(options: dict) -> dict:
    return {"ok": True}


@register("noop_gpu")
def noop_gpu(options: dict) -> dict:
    return {"ok": True}
