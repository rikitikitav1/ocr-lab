import threading
import time
from datetime import timedelta

import job_queue
import pytest
import worker_registry
from orm.db import Session
from orm.jobs import Job

from tests.real_db import needs_db

pytestmark = needs_db


def _status(id: int) -> str:
    with Session() as session:
        return session.get(Job, id).status


def test_two_claimers_never_get_the_same_job(stand):
    ids = [job_queue.enqueue("noop") for _ in range(20)]
    got: list[int] = []
    lock = threading.Lock()

    def claim():
        while (c := job_queue.claim_next("cpu")) is not None:
            with lock:
                got.append(c.id)

    threads = [threading.Thread(target=claim) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(got) == sorted(ids)


def test_lane_comes_from_the_type(stand):
    gpu = job_queue.enqueue("noop_gpu")
    assert job_queue.claim_next("cpu") is None or job_queue.get(gpu).lane == "gpu"
    assert job_queue.get(gpu).lane == "gpu"


def test_unknown_type_and_bad_options_are_refused(stand):
    import job_specs

    with pytest.raises(job_specs.Refused):
        job_queue.enqueue("no_such_type")
    with pytest.raises(job_specs.Refused):
        job_queue.enqueue("intake", {"book_id": "x"})


def test_reschedule_keeps_job_waiting_until_its_time(stand):
    id = job_queue.enqueue("noop")
    claimed = job_queue.claim_next("cpu")
    job_queue.reschedule(claimed.id, timedelta(hours=1), "boom", attempts=1)
    assert _status(id) == "new"
    assert job_queue.claim_next("cpu") is None
    assert job_queue.get(id).waiting_because["error"] == "boom"


def test_stale_running_jobs_are_requeued(stand):
    id = job_queue.enqueue("noop")
    job_queue.claim_next("cpu")
    assert id in job_queue.requeue_stale(["cpu"])
    assert _status(id) == "new"


def test_wait_returns_when_children_finish(stand):
    parent = job_queue.enqueue("noop")
    child = job_queue.enqueue("noop", parent_id=parent)

    def finish():
        time.sleep(0.5)
        job_queue.complete(parent)
        time.sleep(0.5)
        job_queue.complete(child)

    threading.Thread(target=finish).start()
    started = time.monotonic()
    out = job_queue.wait(parent, timeout=10)
    assert out["finished"] is True
    assert time.monotonic() - started < 5


def test_wait_returns_on_timeout(stand):
    id = job_queue.enqueue("noop")
    out = job_queue.wait(id, timeout=0.5)
    assert out["timeout"] is True and out["finished"] is False


def test_budget_is_read_per_stage_and_bounded():
    import job_specs

    assert 3 <= job_specs.attempts_for("assemble_piece") <= 5
    assert all(3 <= v <= 5 for v in job_specs.budgets().values())
    assert set(job_specs.SPECS) <= set(job_specs.budgets())


def test_retry_gives_a_failed_job_a_fresh_budget(stand):
    id = job_queue.enqueue("noop")
    job_queue.claim_next("cpu")
    job_queue.fail(id, {"error": "boom"}, "budget_spent")
    assert job_queue.retry([id]) == [id]
    job = job_queue.get(id)
    assert job.status == "new" and job.attempts == 0 and job.waiting_because["previous_error"]["error"] == "boom"


@needs_db
def test_a_cancel_reaches_queued_children(stand):
    parent = job_queue.enqueue("noop")
    child = job_queue.enqueue("noop", parent_id=parent)
    assert set(job_queue.cancel([parent])) == {parent, child}


@needs_db
def test_a_child_enqueued_after_its_parent_was_cancelled_never_runs(stand):
    parent = job_queue.enqueue("noop")
    job_queue.cancel([parent])
    child = job_queue.enqueue("noop", parent_id=parent)
    assert job_queue.get(child).status == "cancelled"


def test_the_code_hash_covers_config_and_reads_the_source_tree(tmp_path, monkeypatch):
    import code_version

    for root in (tmp_path / "copy", tmp_path / "source"):
        (root / "app").mkdir(parents=True)
        (root / "config").mkdir()
        (root / "app" / "a.py").write_text("x = 1\n")
        (root / "config" / "c.yaml").write_text("k: 1\n")
    same = code_version.tree_hash(tmp_path / "copy")
    assert code_version.tree_hash(tmp_path / "source") == same
    (tmp_path / "source" / "config" / "c.yaml").write_text("k: 2\n")
    assert code_version.tree_hash(tmp_path / "source") != same


def test_a_worker_starting_up_leaves_a_live_worker_s_jobs_in_hand_and_takes_back_a_dead_one_s(stand):
    from orm.db import Session
    from sqlalchemy import text

    mine, theirs, dead = (job_queue.enqueue("noop") for _ in range(3))
    lock = worker_registry.hold_host("alive")
    with Session() as session:
        for host, id in (("me", mine), ("alive", theirs), ("gone", dead)):
            session.execute(text("UPDATE jobs SET status = 'running', claimed_by = :host WHERE id = :id"),
                            {"host": host, "id": id})
        session.execute(text("INSERT INTO workers (host, code, seen_at) VALUES ('gone', 'c', now() - interval "
                             "'1 hour') ON CONFLICT (host) DO UPDATE SET seen_at = now() - interval '1 hour'"))
        session.commit()
    back = job_queue.requeue_stale(["cpu"], "me")
    assert mine in back and dead in back and theirs not in back
    lock.close()


def test_a_running_worker_takes_back_a_dead_worker_s_jobs_and_one_with_no_claimer(stand):
    from orm.db import Session
    from sqlalchemy import text

    worker_registry.heartbeat("me", "c", started=True)
    worker_registry.heartbeat("other", "c", started=True)
    mine, dead, legacy = (job_queue.enqueue("noop") for _ in range(3))
    with Session() as session:
        for host, id in (("me", mine), ("gone", dead), (None, legacy)):
            session.execute(text("UPDATE jobs SET status = 'running', claimed_by = :host, updated_at = now() "
                                 "WHERE id = :id"),
                            {"host": host, "id": id})
        session.commit()
    back = job_queue.requeue_stale(["cpu"], "me", starting=False)
    assert dead in back and mine not in back and legacy in back


def test_a_worker_s_jobs_are_taken_back_only_once_its_host_lock_is_free_and_a_late_beat_takes_none(stand):
    from orm.db import Session
    from sqlalchemy import text

    held, free = job_queue.enqueue("noop"), job_queue.enqueue("noop")
    lock = worker_registry.hold_host("alive-host")
    with Session() as session:
        for host, id in (("alive-host", held), ("dead-host", free)):
            session.execute(text("UPDATE jobs SET status = 'running', claimed_by = :host WHERE id = :id"),
                            {"host": host, "id": id})
        session.commit()
    assert job_queue.requeue_stale(["cpu"], "me", starting=False, foreign=False) == []
    back = job_queue.requeue_stale(["cpu"], "me", starting=False)
    assert free in back and held not in back
    lock.close()


def test_a_late_outcome_of_a_worker_whose_job_was_taken_back_leaves_the_new_claimant_s_job_alone(stand):
    from orm.db import Session
    from sqlalchemy import text

    id = job_queue.enqueue("noop")
    with Session() as session:
        session.execute(text("UPDATE jobs SET status = 'running', claimed_by = 'second' WHERE id = :id"), {"id": id})
        session.commit()
    assert not job_queue.complete(id, 1.0, {"by": "first"}, claimant="first")
    assert not job_queue.reschedule(id, timedelta(seconds=1), "late", claimant="first")
    job = job_queue.get(id)
    assert job.status == "running" and job.claimed_by == "second" and job.result is None
    assert job_queue.complete(id, 1.0, {"by": "second"}, claimant="second") and job_queue.get(id).status == "done"


def test_a_worker_silent_for_a_day_is_forgotten_and_a_recent_dead_one_stays_listed(stand):
    from orm.db import Session
    from sqlalchemy import text

    worker_registry.heartbeat("long-gone", "c")
    worker_registry.heartbeat("just-gone", "c")
    with Session() as session:
        session.execute(text("UPDATE workers SET seen_at = now() - interval '2 days' WHERE host = 'long-gone'"))
        session.execute(text("UPDATE workers SET seen_at = now() - interval '10 minutes' WHERE host = 'just-gone'"))
        session.commit()
    worker_registry.heartbeat("me", "c")
    listed = worker_registry.workers()
    assert "long-gone" not in listed and "just-gone" in listed and not listed["just-gone"]["alive"]
