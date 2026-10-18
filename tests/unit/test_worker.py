import job_handlers
import job_queue
import worker
import worker_registry
from orm.db import Session
from orm.jobs import Job

from tests.real_db import needs_db

pytestmark = needs_db


def test_a_failing_job_stops_after_its_stage_budget(stand, monkeypatch):
    import job_specs

    monkeypatch.setitem(job_handlers.HANDLERS, "noop", lambda o: 1 / 0)
    monkeypatch.setattr(job_specs, "attempts_for", lambda t: 3)
    id = job_queue.enqueue("noop")
    for _ in range(3):
        with Session() as session:
            session.get(Job, id).apply_since = session.get(Job, id).created_at
            session.commit()
        assert worker.run_once("cpu")
    job = job_queue.get(id)
    assert job.status == "error"
    assert job.error["kind"] == "budget_spent" and job.error["attempts"] == 3


def test_deferred_does_not_spend_an_attempt(stand, monkeypatch):
    def defer(options):
        raise job_handlers.Deferred("model down", delay_seconds=1)

    monkeypatch.setitem(job_handlers.HANDLERS, "noop", defer)
    id = job_queue.enqueue("noop")
    assert worker.run_once("cpu")
    job = job_queue.get(id)
    assert job.status == "new" and job.attempts == 0 and job.waiting_because["kind"] == "deferred"


@needs_db
def test_a_deferred_job_runs_on_its_next_claim(stand, monkeypatch):
    calls = []

    def handler(options):
        calls.append(1)
        if len(calls) == 1:
            raise job_handlers.Deferred("model away", delay_seconds=1)
        return {"ok": True}

    monkeypatch.setitem(job_handlers.HANDLERS, "noop", handler)
    id = job_queue.enqueue("noop")
    assert worker.run_once("cpu")
    with Session() as session:
        session.get(Job, id).apply_since = session.get(Job, id).created_at
        session.commit()
    assert worker.run_once("cpu")
    job = job_queue.get(id)
    assert job.status == "done" and job.deferred_seconds == 1 and "_deferred_seconds" not in job.options


def test_the_worker_moves_to_newer_code_only_when_nothing_is_running_or_due(monkeypatch):
    exits = []
    monkeypatch.setitem(worker._held, "stopping", False)
    monkeypatch.setattr(worker.os, "_exit", lambda code: exits.append(code))
    monkeypatch.setattr(worker.code_version, "differs_from_disk", lambda: True)
    monkeypatch.setattr(worker.code_version, "reload_requested", lambda host=None: False)
    monkeypatch.setattr(job_queue, "has_due", lambda lanes=None: True)
    worker._restart_if_behind()
    assert exits == []
    monkeypatch.setattr(job_queue, "has_due", lambda lanes=None: False)
    monkeypatch.setitem(worker._held, "running", 1)
    worker._restart_if_behind()
    assert exits == []
    monkeypatch.setitem(worker._held, "running", 0)
    worker._restart_if_behind()
    assert exits == [0]


def test_an_asked_reload_stops_claiming_at_once_and_restarts_when_the_jobs_in_hand_end(monkeypatch, tmp_path):
    import settings

    exits, claims = [], []
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    monkeypatch.setitem(worker._held, "stopping", False)
    monkeypatch.setitem(worker._held, "running", 1)
    monkeypatch.setattr(worker.os, "_exit", lambda code: exits.append(code))
    monkeypatch.setattr(worker.code_version, "differs_from_disk", lambda: True)
    monkeypatch.setattr(job_queue, "has_due", lambda lanes=None: True)
    monkeypatch.setattr(job_queue, "claim_next", lambda lane, code, host=None: claims.append(lane))
    worker.code_version.request_reload([worker.HOST])
    assert worker.run_once("cpu") is False
    assert exits == [] and claims == [] and worker._held["stopping"]
    monkeypatch.setitem(worker._held, "running", 0)
    assert worker.run_once("gpu") is False
    assert exits == [0] and claims == [] and not worker.code_version.reload_requested(worker.HOST)


def test_a_reload_asked_with_nothing_newer_on_disk_is_dropped(monkeypatch, tmp_path):
    import settings

    exits = []
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    monkeypatch.setitem(worker._held, "stopping", False)
    monkeypatch.setattr(worker.os, "_exit", lambda code: exits.append(code))
    monkeypatch.setattr(worker.code_version, "differs_from_disk", lambda: False)
    worker.code_version.request_reload([worker.HOST])
    worker._restart_if_behind()
    assert exits == [] and not worker._held["stopping"] and not worker.code_version.reload_requested(worker.HOST)


def test_a_job_s_log_lines_name_its_run_and_book(monkeypatch):
    import structlog

    seen = []
    monkeypatch.setattr(worker, "_run", lambda claimed: seen.append(structlog.contextvars.get_contextvars()))
    worker._claimed(job_queue.ClaimedJob(7, "noop", {}, 0, 0, 11, 13), "cpu")
    assert seen == [{"job_id": 7, "job_type": "noop", "run_id": 11, "book_id": 13}]
    assert structlog.contextvars.get_contextvars() == {}


def test_the_worker_beats_while_its_lanes_are_busy(monkeypatch):
    beats = []

    def sleep(seconds):
        raise StopIteration

    monkeypatch.setattr(worker_registry, "heartbeat", lambda host, code, lanes=(): beats.append(code))
    # the beat runs with no database: the locks and the takeback are faked, only the heartbeat is watched
    monkeypatch.setattr(worker, "_keep_alive", lambda: None)
    monkeypatch.setattr(worker, "_keep_gpu", lambda: None)
    monkeypatch.setattr(worker.job_queue, "requeue_stale", lambda *a, **kw: [])
    monkeypatch.setattr(worker.time, "sleep", sleep)
    try:
        worker._beat()
    except StopIteration:
        pass
    assert beats == [worker.code_version.LOADED]


def test_a_started_worker_without_the_gpu_lane_never_claims_from_it(monkeypatch):
    claims = []
    monkeypatch.setitem(worker._gpu, "held", False)
    monkeypatch.setitem(worker._held, "stopping", False)
    monkeypatch.setattr(worker.code_version, "reload_requested", lambda host=None: False)
    monkeypatch.setattr(job_queue, "claim_next", lambda lane, code, host=None: claims.append(lane))
    assert worker.run_once("gpu") is False and claims == []
