import threading
import time
from datetime import timedelta

import job_queue
import pytest
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

    assert 3 <= job_specs.attempts_for("assemble_chapter") <= 5
    assert all(3 <= v <= 5 for v in job_specs.budgets().values())


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
