import json

import code_version
import settings
from orm.db import Session
from sqlalchemy import text
from stages.toc import collect

from tests.doors.test_runs import TEXT, _drain, engines
from tests.fixtures import build, text_page
from tests.real_db import needs_db

pytestmark = needs_db


def _book(client, inbox, name: str) -> int:
    pages = [text_page("One", TEXT, bookmark="One"), text_page("Two", TEXT, bookmark="Two")]
    return client.post("/v1/books", json={"file_paths": [str(build(inbox / name, pages))], "then": []}).json()["id"]


def test_a_page_range_read_through_one_engine_is_kept_and_readable_by_its_artifact(client, inbox, monkeypatch):
    book = _book(client, inbox, "range.pdf")
    engines(monkeypatch)
    assert client.post(f"/v1/books/{book}/read_range", json={"engine": "mineru", "first_page": 2,
                                                              "last_page": 3}).status_code == 400
    assert client.post(f"/v1/books/{book}/read_range", json={"engine": "nope", "first_page": 1,
                                                              "last_page": 2}).status_code == 400
    job = client.post(f"/v1/books/{book}/read_range", json={"engine": "mineru", "first_page": 1, "last_page": 2})
    assert job.status_code == 202
    _drain()
    done = client.get(f"/v1/jobs/{job.json()['job_id']}").json()
    assert done["status"] == "done" and done["lane"] == "gpu" and done["book_id"] == book
    (key, artifact_id), = done["result"]["readings"].items()
    assert key.startswith("mineru:0:1-2")
    kept = client.get(f"/v1/artifacts/{artifact_id}").json()
    assert kept["book_id"] == book and TEXT in kept["text"]
    assert client.get(f"/v1/artifacts/{artifact_id + 10_000}").status_code == 404


def test_reassembly_with_a_knob_reports_each_chapter_before_and_after_and_leaves_the_run_alone(client, inbox,
                                                                                             monkeypatch):
    book = _book(client, inbox, "reassemble.pdf")
    collect.collect(book)
    engines(monkeypatch)
    run_id = client.post(f"/v1/books/{book}/runs", json={}).json()["run"]["id"]
    _drain()
    kept = client.get(f"/v1/runs/{run_id}/artifacts").json()
    chapters = client.get(f"/v1/runs/{run_id}/chapters").json()
    assert client.post(f"/v1/runs/{run_id}/reassemble", json={"knobs": {"assembly.nope": True}}).status_code == 400
    assert client.post(f"/v1/runs/{run_id}/reassemble", json={"knobs": {}}).status_code == 400
    job = client.post(f"/v1/runs/{run_id}/reassemble", json={"knobs": {"assembly.tables_from": None},
                                                             "ords": [2, 9]})
    assert job.status_code == 202
    _drain()
    done = client.get(f"/v1/jobs/{job.json()['job_id']}").json()
    assert done["status"] == "done" and done["lane"] == "cpu" and done["run_id"] is None
    result = done["result"]
    assert result["skipped"] == [9] and [c["ord"] for c in result["chapters"]] == [2]
    assert result["chapters_changed"] == [2] and result["chapters"][0]["changed"] == ["passes.tables_swapped"]
    assert "lost_text" in result["chapters"][0]["before"]
    scratch = settings.DATA_DIR / "scratch" / "reassemble" / f"job-{done['id']}.json"
    assert json.loads(scratch.read_text())["chapters_changed"] == [2]
    assert client.get(f"/v1/runs/{run_id}/artifacts").json() == kept
    assert client.get(f"/v1/runs/{run_id}/chapters").json() == chapters


def test_a_worker_reload_is_asked_only_when_the_worker_runs_older_code(client):
    asked = client.post("/v1/stand/worker/reload").json()
    assert asked["requested"] is False and asked["because"] == "no worker seen"
    with Session() as session:
        session.execute(text("INSERT INTO workers (host, code) VALUES ('w', :code)"),
                        {"code": code_version.tree_hash()})
        session.commit()
    assert client.post("/v1/stand/worker/reload").json()["requested"] is False
    assert not code_version.reload_requested()
    with Session() as session:
        session.execute(text("UPDATE workers SET code = 'older', seen_at = now()"))
        session.commit()
    assert client.post("/v1/stand/worker/reload").json()["requested"] is True
    assert code_version.reload_requested()
