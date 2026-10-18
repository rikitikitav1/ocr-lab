import job_queue
import settings
import worker_registry

from tests.real_db import needs_db

pytestmark = needs_db


def test_jobs_doors(stand, client):
    id = job_queue.enqueue("noop")
    assert client.get(f"/v1/jobs/{id}").json()["status"] == "new"
    assert client.post("/v1/jobs/pause", json={"ids": [id]}).json()["changed"] == [id]
    assert client.post("/v1/jobs/resume", json={"ids": [id]}).json()["changed"] == [id]
    assert client.post("/v1/jobs/cancel", json={"ids": [id]}).json()["changed"] == [id]
    assert client.get(f"/v1/jobs/{id}/wait", params={"timeout": 1}).json()["finished"] is True
    assert client.get("/v1/jobs/999999").status_code == 404
    assert "lanes" in client.get("/v1/queue").json()


def test_job_types_name_their_lane_options_budget_and_whether_the_worker_runs_them(client):
    types = {t["type"]: t for t in client.get("/v1/job_types").json()}
    assert types["read_piece"]["lane"] == "gpu" and types["read_piece"]["attempts"] == 5
    assert {"run_id", "ord", "engine"} <= set(types["read_piece"]["options"]["properties"])
    assert types["read_piece"]["built"] and not types["profile_search"]["built"]


def test_the_stand_names_the_code_a_live_worker_runs_even_when_it_is_idle(client):
    from orm.db import Session
    from sqlalchemy import text

    worker_registry.heartbeat("worker-under-test", "abc123", started=True)
    # a worker thread left by another test may beat too; this one is made the latest so the stand must report it
    with Session() as session:
        session.execute(text("UPDATE workers SET seen_at = now() + interval '1 hour' WHERE host = 'worker-under-test'"))
        session.commit()
    db = client.get("/v1/stand").json()["db"]
    assert db["last_worker_code"] == "abc123"


def test_the_queue_shows_the_work_in_flight_and_prices_it_by_each_type_s_recent_jobs(stand, client):
    from orm.db import Session
    from orm.jobs import Job

    with Session() as session:
        session.add_all([Job(type="noop", lane="cpu", status="done", elapsed=e) for e in (2.0, 4.0, 6.0)])
        session.commit()
    waiting = [job_queue.enqueue("noop", book_id=None) for _ in range(3)]
    seen = client.get("/v1/queue", params={"types": ["noop"]}).json()
    assert seen["in_flight"]["cpu"]["noop"]["new"] == 3 and seen["running"] == []
    assert seen["seconds_left"]["cpu"] == round(3 * 4.0 / settings.CPU_LANE_THREADS)
    assert client.get("/v1/queue", params={"types": ["intake"]}).json()["in_flight"] == {}
    cost = {t["type"]: t["cost"] for t in client.get("/v1/job_types").json()}["noop"]
    assert cost == {"jobs": 3, "median": 4.0, "p90": 6.0}
    client.post("/v1/jobs/cancel", json={"ids": waiting})


def test_a_read_that_took_kept_readings_is_priced_apart_and_a_queued_read_at_the_real_price(stand, client):
    from orm.db import Session
    from orm.jobs import Job

    with Session() as session:
        done = [(1.0, True), (1.0, True), (1.0, True), (60.0, False), (80.0, False), (2.0, None)]
        session.add_all([Job(type="noop", lane="cpu", status="done", elapsed=e,
                             result=None if kept is None else {"kept": kept}) for e, kept in done])
        session.commit()
    waiting = [job_queue.enqueue("noop", book_id=None)]
    row = {t["type"]: t for t in client.get("/v1/job_types").json()}["noop"]
    assert row["cost"]["median"] == 80.0 and row["cost_kept"]["median"] == 1
    assert client.get("/v1/queue", params={"types": ["noop"]}).json()["seconds_left"]["cpu"] == \
        round(80.0 / settings.CPU_LANE_THREADS)
    client.post("/v1/jobs/cancel", json={"ids": waiting})


def test_jobs_filter_by_lists_and_parent_and_page_in_brief_rows(stand, client):
    parent = job_queue.enqueue("noop")
    kids = [job_queue.enqueue("noop", parent_id=parent) for _ in range(3)]
    other = job_queue.enqueue("noop_gpu")
    both = client.get("/v1/jobs", params={"type": ["noop", "noop_gpu"], "status": ["new"], "brief": True}).json()
    assert {parent, other, *kids} <= {j["id"] for j in both} and "result" not in both[0] and "options" not in both[0]
    under = client.get("/v1/jobs", params={"parent_id": parent}).json()
    assert sorted(j["id"] for j in under) == kids
    page = client.get("/v1/jobs", params={"parent_id": parent, "limit": 2}).json()
    rest = client.get("/v1/jobs", params={"parent_id": parent, "before_id": page[-1]["id"]}).json()
    assert [j["id"] for j in page + rest] == sorted(kids, reverse=True)
    client.post("/v1/jobs/cancel", json={"ids": [parent, other, *kids]})
