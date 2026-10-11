import faulthandler
import os
import socket
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
from stages import run_state

log = logging_setup.get_logger(__name__)

POLL_SECONDS = 3
# a deferral is not a failure, so it has a ceiling of its own, in seconds waited
MAX_DEFERRED_SECONDS = 3600
LANES = ("gpu", "cpu")
HEARTBEAT_SECONDS = 30


_held = {"running": 0, "stopping": False}
_held_lock = threading.Lock()


# newer code on disk waits until nothing is left to claim, or, when asked, until the jobs in hand end
def _restart_if_behind() -> None:
    asked = code_version.reload_requested()
    with _held_lock:
        if not _held["stopping"]:
            if not asked and _held["running"]:
                return
            if not code_version.differs_from_disk():
                if asked:
                    code_version.clear_reload()
                return
            if not asked and job_queue.has_due():
                return
            # no lane claims from here on, so the jobs in hand are the last on the old code
            _held["stopping"] = True
        if _held["running"]:
            return
    code_version.clear_reload()
    log.info("worker.restart", reason="newer code on disk", asked=asked)
    os._exit(0)


def run_once(lane: str) -> bool:
    if _held["stopping"] or code_version.reload_requested():
        _restart_if_behind()
    with _held_lock:
        if _held["stopping"]:
            return False
        _held["running"] += 1
    try:
        claimed = job_queue.claim_next(lane, code_version.LOADED)
        if claimed is not None:
            _claimed(claimed, lane)
    finally:
        with _held_lock:
            _held["running"] -= 1
    if claimed is None:
        # an idle cpu lane settles runs whose chapters died with a worker or a cancel
        if lane == "cpu":
            run_state.settle()
        _restart_if_behind()
        return False
    return True


# the worker beats from a thread of its own, so a long job never reads as a dead worker on the stand
def _beat() -> None:
    while True:
        try:
            job_queue.heartbeat(socket.gethostname(), code_version.LOADED)
        except Exception as e:
            log.error("worker.heartbeat_failed", error=str(e))
        time.sleep(HEARTBEAT_SECONDS)


def _claimed(claimed: job_queue.ClaimedJob, lane: str) -> None:
    structlog.contextvars.bind_contextvars(job_id=claimed.id, job_type=claimed.type, run_id=claimed.run_id,
                                           book_id=claimed.book_id)
    parent = job_queue.running_job.set(claimed.id)
    on_lane = job_queue.running_lane.set(lane)
    try:
        _run(claimed)
    finally:
        job_queue.running_lane.reset(on_lane)
        job_queue.running_job.reset(parent)
        structlog.contextvars.unbind_contextvars("job_id", "job_type", "run_id", "book_id")


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
        _ended(claimed.type, options, "done", None)
    except job_handlers.Deferred as d:
        waited = claimed.deferred_seconds + d.delay_seconds
        if waited > MAX_DEFERRED_SECONDS:
            error = f"waited {waited}s and gave up: {d}"
            job_queue.fail(claimed.id, {"error": error}, "deferred_out")
            _ended(claimed.type, options, "error", error)
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
            _ended(claimed.type, options, "error", str(e))


def _ended(type: str, options: dict, outcome: str, error: str | None) -> None:
    if (ended := job_handlers.ENDED.get(type)) is None:
        return
    try:
        ended(options, outcome, error)
    except Exception as e:
        log.error("worker.ended_failed", type=type, error=str(e))


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
    job_queue.heartbeat(socket.gethostname(), code_version.LOADED, started=True)
    log.info("worker.start", code=code_version.LOADED, handlers=sorted(job_handlers.HANDLERS), requeued=stale)
    threading.Thread(target=_beat, daemon=True).start()
    for _ in range(settings.CPU_LANE_THREADS):
        threading.Thread(target=_loop, args=("cpu",), daemon=True).start()
    # the GPU lane is one thread: two card jobs never run at once
    _loop("gpu")


if __name__ == "__main__":
    main()
