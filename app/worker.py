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
import worker_registry
from knobs import registry
from stages import run_state

log = logging_setup.get_logger(__name__)

POLL_SECONDS = 3
# a deferral is not a failure, so it has a ceiling of its own, in seconds waited
MAX_DEFERRED_SECONDS = 3600
HOST = socket.gethostname()
# None until a started worker settles it: a lane driven directly (a test, a script) is not held back
_gpu = {"held": None, "connection": None}
# the lock that tells other workers this one is alive, and when it last beat by the wall clock
_me = {"connection": None, "beat_at": None, "held_since": None}


_held = {"running": 0, "stopping": False}
_held_lock = threading.Lock()


# newer code on disk waits until nothing is left to claim, or, when asked, until the jobs in hand end
def _restart_if_behind() -> None:
    asked = code_version.reload_requested(HOST)
    with _held_lock:
        if not _held["stopping"]:
            if not asked and _held["running"]:
                return
            if not code_version.differs_from_disk():
                if asked:
                    code_version.clear_reload(HOST)
                return
            if not asked and job_queue.has_due(_lanes()):
                return
            # no lane claims from here on, so the jobs in hand are the last on the old code
            _held["stopping"] = True
        if _held["running"]:
            return
    code_version.clear_reload(HOST)
    log.info("worker.restart", reason="newer code on disk", asked=asked)
    os._exit(0)


def run_once(lane: str) -> bool:
    if _held["stopping"] or code_version.reload_requested(HOST):
        _restart_if_behind()
    if lane == "gpu" and _gpu["held"] is False:
        # a worker waiting for the GPU lane still takes newer code
        _restart_if_behind()
        return False
    with _held_lock:
        if _held["stopping"]:
            return False
        _held["running"] += 1
    try:
        claimed = job_queue.claim_next(lane, code_version.LOADED, HOST)
        if claimed is not None:
            _claimed(claimed, lane)
    finally:
        with _held_lock:
            _held["running"] -= 1
    if claimed is None:
        # an idle cpu lane settles runs whose pieces died with a worker or a cancel
        if lane == "cpu":
            run_state.settle()
        _restart_if_behind()
        return False
    return True


# the worker beats from a thread of its own, so a long job never reads as a dead worker on the stand
def _beat() -> None:
    while True:
        try:
            # after a pause every worker's beat is late; others get a beat to show they live before their jobs go
            late = _me["beat_at"] is not None and time.time() - _me["beat_at"] > 2 * worker_registry.HEARTBEAT_SECONDS
            _keep_alive()
            worker_registry.heartbeat(HOST, code_version.LOADED, lanes=tuple(_lanes()))
            _me["beat_at"] = time.time()
            _keep_gpu()
            # a lock taken again (the database restarted and every lock went) waits two beats for the others to retake
            held = _me["held_since"]
            settled = held is not None and time.time() - held > 2 * worker_registry.HEARTBEAT_SECONDS
            job_queue.requeue_stale(_lanes(), HOST, starting=False, foreign=not late and settled)
        except Exception as e:
            log.error("worker.heartbeat_failed", error=str(e))
        time.sleep(worker_registry.HEARTBEAT_SECONDS)


# a worker set to serve the GPU lane takes it when no other holds it, and lets it go if its lock's connection dies
def _keep_gpu() -> None:
    if "gpu" not in settings.WORKER_LANES:
        return
    if _gpu["held"] and not worker_registry.lock_held(_gpu["connection"]):
        log.error("worker.gpu_lost", because="the GPU lane lock's connection is gone")
        _gpu["held"], _gpu["connection"] = False, None
    if not _gpu["held"]:
        connection = worker_registry.hold_gpu_lane()
        _gpu["held"], _gpu["connection"] = connection is not None, connection
        if connection is not None:
            log.info("worker.gpu_taken")


def _keep_alive() -> None:
    if _me["connection"] is not None and not worker_registry.lock_held(_me["connection"]):
        _me["connection"] = None
    if _me["connection"] is None:
        _me["connection"] = worker_registry.hold_host(HOST)
        _me["held_since"] = time.time() if _me["connection"] is not None else None


def _lanes() -> list[str]:
    return [lane for lane in settings.WORKER_LANES if lane != "gpu" or _gpu["held"] is not False]


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
        job_queue.fail(claimed.id, {"error": f"no handler for {claimed.type}"}, "no_handler", claimant=HOST)
        return
    try:
        options = job_specs.check(claimed.type, claimed.options)
    except job_specs.Refused as bad:
        job_queue.fail(claimed.id, {"error": str(bad)}, "refused", claimant=HOST)
        return
    started = time.perf_counter()
    try:
        returned = handler(options | {"_job_id": claimed.id, "_run_id": claimed.run_id, "_book_id": claimed.book_id})
        elapsed = round(time.perf_counter() - started, 3)
        if not job_queue.complete(claimed.id, elapsed, returned if isinstance(returned, dict) else None, HOST):
            log.error("worker.outcome_dropped", because="another worker took the job back")
            return
        log.info("worker.done", elapsed=elapsed)
        _ended(claimed.type, options, "done", None)
    except job_handlers.Deferred as d:
        waited = claimed.deferred_seconds + d.delay_seconds
        if waited > MAX_DEFERRED_SECONDS:
            error = f"waited {waited}s and gave up: {d}"
            if job_queue.fail(claimed.id, {"error": error}, "deferred_out", claimant=HOST):
                _ended(claimed.type, options, "error", error)
            return
        job_queue.reschedule(claimed.id, timedelta(seconds=d.delay_seconds), str(d), kind="deferred",
                             deferred_seconds=waited, claimant=HOST)
    except Exception as e:
        elapsed = round(time.perf_counter() - started, 3)
        attempts = claimed.attempts + 1
        budget = job_specs.attempts_for(claimed.type)
        if attempts < budget and not isinstance(e, job_handlers.Final):
            job_queue.reschedule(claimed.id, timedelta(seconds=60 * attempts), str(e), attempts=attempts,
                                 elapsed=elapsed, claimant=HOST)
            log.error("worker.retry", attempts=attempts, budget=budget, error=str(e))
        else:
            kind = "final" if isinstance(e, job_handlers.Final) else "budget_spent"
            settled = job_queue.fail(claimed.id, {"error": str(e), "attempts": attempts, "budget": budget,
                                                  "trace": traceback.format_exc(limit=5)}, kind, elapsed, HOST)
            log.error("worker.failed", attempts=attempts, error=str(e))
            if settled:
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
    registry.validate()
    unknown = set(settings.WORKER_LANES) - {"cpu", "gpu"}
    if unknown or not settings.WORKER_LANES:
        raise SystemExit(f"WORKER_LANES names no lane or lanes it does not know: {sorted(unknown)}")
    _gpu["held"] = False
    _keep_gpu()
    if "gpu" in settings.WORKER_LANES and not _gpu["held"]:
        log.error("worker.gpu_taken_elsewhere", because="another worker holds the GPU lane; this one waits for it")
    _keep_alive()
    # this host's last life held jobs in every lane it serves, whether or not it holds the GPU now
    stale = job_queue.requeue_stale(settings.WORKER_LANES, HOST)
    worker_registry.heartbeat(HOST, code_version.LOADED, started=True, lanes=tuple(_lanes()))
    _me["beat_at"] = time.time()
    log.info("worker.start", code=code_version.LOADED, handlers=sorted(job_handlers.HANDLERS), requeued=stale,
             lanes=_lanes())
    threading.Thread(target=_beat, daemon=True).start()
    for _ in range(settings.CPU_LANE_THREADS if "cpu" in settings.WORKER_LANES else 0):
        threading.Thread(target=_loop, args=("cpu",), daemon=True).start()
    # the GPU lane is one thread: two card jobs never run at once; a worker with no lane of its own waits on it
    _loop("gpu")


if __name__ == "__main__":
    main()
