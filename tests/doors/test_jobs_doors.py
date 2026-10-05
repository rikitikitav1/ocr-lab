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
