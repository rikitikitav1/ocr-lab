import job_queue

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
    assert types["read_chapter"]["lane"] == "gpu" and types["read_chapter"]["attempts"] == 5
    assert {"run_id", "ord", "engine"} <= set(types["read_chapter"]["options"]["properties"])
    assert types["read_chapter"]["built"] and not types["profile_search"]["built"]


def test_the_stand_names_the_code_a_live_worker_runs_even_when_it_is_idle(client):
    import job_queue
    from orm.db import Session
    from sqlalchemy import text

    job_queue.heartbeat("worker-under-test", "abc123", started=True)
    # a worker thread left by another test may beat too; this one is made the latest so the stand must report it
    with Session() as session:
        session.execute(text("UPDATE workers SET seen_at = now() + interval '1 hour' WHERE host = 'worker-under-test'"))
        session.commit()
    db = client.get("/v1/stand").json()["db"]
    assert db["last_worker_code"] == "abc123"
