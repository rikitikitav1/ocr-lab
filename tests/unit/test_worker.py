import job_handlers
import job_queue
import worker
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
