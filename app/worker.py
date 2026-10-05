import faulthandler
import threading
import time
import traceback
from datetime import timedelta

import code_version
import job_handlers
import job_queue
import job_specs
import logging_setup
import settings
import structlog

log = logging_setup.get_logger(__name__)

POLL_SECONDS = 3
# a deferral is not a failure, so it has a ceiling of its own, in seconds waited
MAX_DEFERRED_SECONDS = 3600
LANES = ("gpu", "cpu")


def run_once(lane: str) -> bool:
    # an edit under a running worker: it stops claiming until restarted, and the stand door says why
    if code_version.differs_from_disk():
        return False
    claimed = job_queue.claim_next(lane, code_version.LOADED)
    if claimed is None:
        return False
    structlog.contextvars.bind_contextvars(job_id=claimed.id, job_type=claimed.type)
    parent = job_queue.running_job.set(claimed.id)
    try:
        _run(claimed)
    finally:
        job_queue.running_job.reset(parent)
        structlog.contextvars.unbind_contextvars("job_id", "job_type")
    return True


def _run(claimed: job_queue.ClaimedJob) -> None:
    handler = job_handlers.HANDLERS.get(claimed.type)
    if handler is None:
        job_queue.fail(claimed.id, {"error": f"no handler for {claimed.type}"}, "no_handler")
        return
    try:
        options = job_specs.check(claimed.type, claimed.options)
    except job_specs.Refused as bad:
        job_queue.fail(claimed.id, {"error": str(bad)}, "refused")
        return
    started = time.perf_counter()
    try:
        returned = handler(options | {"_job_id": claimed.id, "_run_id": claimed.run_id, "_book_id": claimed.book_id})
        elapsed = round(time.perf_counter() - started, 3)
        job_queue.complete(claimed.id, elapsed, returned if isinstance(returned, dict) else None)
        log.info("worker.done", elapsed=elapsed)
    except job_handlers.Deferred as d:
        waited = claimed.deferred_seconds + d.delay_seconds
        if waited > MAX_DEFERRED_SECONDS:
            job_queue.fail(claimed.id, {"error": f"waited {waited}s and gave up: {d}"}, "deferred_out")
            return
        job_queue.reschedule(claimed.id, timedelta(seconds=d.delay_seconds), str(d), kind="deferred",
                             deferred_seconds=waited)
    except Exception as e:
        elapsed = round(time.perf_counter() - started, 3)
        attempts = claimed.attempts + 1
        budget = job_specs.attempts_for(claimed.type)
        if attempts < budget and not isinstance(e, job_handlers.Final):
            job_queue.reschedule(claimed.id, timedelta(seconds=60 * attempts), str(e), attempts=attempts,
                                 elapsed=elapsed)
            log.error("worker.retry", attempts=attempts, budget=budget, error=str(e))
        else:
            kind = "final" if isinstance(e, job_handlers.Final) else "budget_spent"
            job_queue.fail(claimed.id, {"error": str(e), "attempts": attempts, "budget": budget,
                                        "trace": traceback.format_exc(limit=5)}, kind, elapsed)
            log.error("worker.failed", attempts=attempts, error=str(e))


def _loop(lane: str) -> None:
    while True:
        try:
            busy = run_once(lane)
        except Exception as e:
            log.error("worker.loop_error", lane=lane, error=str(e))
            busy = False
        if not busy:
            time.sleep(POLL_SECONDS)


def main() -> None:
    logging_setup.configure(settings.LOG_LEVEL)
    # a crash in native code (PDFium) kills the process with no trace otherwise
    faulthandler.enable(all_threads=True)
    job_handlers.load_all()
    job_specs.budgets()
    stale = job_queue.requeue_stale(list(LANES))
    log.info("worker.start", code=code_version.LOADED, handlers=sorted(job_handlers.HANDLERS), requeued=stale)
    for _ in range(settings.CPU_LANE_THREADS):
        threading.Thread(target=_loop, args=("cpu",), daemon=True).start()
    # the GPU lane is one thread: two card jobs never run at once
    _loop("gpu")


if __name__ == "__main__":
    main()
