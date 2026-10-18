import json

import code_version
import settings
from orm.db import Session
from sqlalchemy import text
from stages import intake
from stages.structure import collect

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


def test_a_raster_reading_takes_every_page_as_a_picture_and_is_kept_with_the_scans_readings(client, inbox,
                                                                                           monkeypatch):
    from engines import reading

    book = _book(client, inbox, "raster.pdf")
    engines(monkeypatch)
    monkeypatch.setattr(reading, "build", lambda engine: "test-build")
    url = f"/v1/books/{book}/read_range"
    pages = {"first_page": 1, "last_page": 2, "force_raster_only": True}
    assert client.post(url, json={"engine": "docling", **pages}).status_code == 400
    job = client.post(url, json={"engine": "mineru", **pages}).json()
    _drain()
    done = client.get(f"/v1/jobs/{job['job_id']}").json()
    assert done["status"] == "done" and done["result"]["force_raster_only"] and done["result"]["pages_read"] > 0
    assert done["result"]["readings"] == ["contents_ocr.0.1-2.json"]
    assert (settings.DATA_DIR / "books" / str(book) / "structure" / "contents_ocr.0.1-2.json").exists()


def test_reassembly_with_a_knob_reports_each_chapter_before_and_after_and_leaves_the_run_alone(client, inbox,
                                                                                             monkeypatch):
    book = _book(client, inbox, "reassemble.pdf")
    intake.probe(book)
    collect.collect(book)
    engines(monkeypatch)
    run_id = client.post(f"/v1/books/{book}/runs", json={}).json()["run"]["id"]
    _drain()
    kept = client.get(f"/v1/runs/{run_id}/artifacts").json()
    pieces = client.get(f"/v1/runs/{run_id}/nodes").json()
    # the book's artifacts the run was made from are listed beside its own and read through the run's door
    made_from = [a for a in client.get(f"/v1/runs/{run_id}/artifacts", params={"used": True}).json() if a.get("used")]
    assert {"probe.json", "nodes.json"} <= {a["name"] for a in made_from}
    readings = [a for a in made_from if a["name"].startswith("reading.")]
    assert readings and all(a["piece"] is not None for a in readings)
    assert client.get(f"/v1/runs/{run_id}/artifacts/{readings[0]['id']}").status_code == 200
    assert client.post(f"/v1/runs/{run_id}/reassemble", json={"knobs": {"assembly.nope": True}}).status_code == 400
    same = client.post(f"/v1/runs/{run_id}/reassemble", json={"knobs": {}})
    assert same.status_code == 202
    job = client.post(f"/v1/runs/{run_id}/reassemble", json={"knobs": {"assembly.tables_from": None},
                                                             "ords": [2, 9]})
    assert job.status_code == 202
    _drain()
    done = client.get(f"/v1/jobs/{job.json()['job_id']}").json()
    assert done["status"] == "done" and done["lane"] == "cpu" and done["run_id"] is None
    result = done["result"]
    assert result["skipped"] == [9] and [c["ord"] for c in result["pieces"]] == [2]
    assert result["pieces_changed"] == [2] and result["pieces"][0]["changed"] == ["passes.tables_swapped"]
    assert "lost_text" in result["pieces"][0]["before"]
    assert result["kept_text_changed"] == [] and result["kept_numbers_changed"] == []
    assert result["pieces"][0]["against_kept"]["lines"] == []
    against = client.get(f"/v1/jobs/{same.json()['job_id']}").json()["result"]
    assert against["pieces_changed"] == [] and against["kept_text_changed"] == [] and against["pieces"]
    scratch = settings.DATA_DIR / "scratch" / "reassemble" / f"job-{done['id']}.json"
    assert json.loads(scratch.read_text())["pieces_changed"] == [2]
    level = client.post(f"/v1/runs/{run_id}/reassemble", json={"knobs": {}, "reading_level": 0, "reread": True})
    _drain()
    by_tree = client.get(f"/v1/jobs/{level.json()['job_id']}").json()["result"]
    assert (by_tree["reading_level"], by_tree["reread"]) == (0, True) and by_tree["pieces"]
    assert "passes.placed_top" in by_tree["pieces"][0]["before"]
    assert by_tree["units_not_pieces"] == [] and by_tree["not_kept"] == {}
    # a piece's read job leaves its tail page to the next piece, so the cut without it is rebuilt from kept readings
    tails = client.post(f"/v1/runs/{run_id}/reassemble", json={"knobs": {}, "reading_level": 0, "reread": False})
    _drain()
    no_tail = client.get(f"/v1/jobs/{tails.json()['job_id']}").json()
    assert no_tail["status"] == "done", no_tail["error"]
    rebuilt = {c["ord"] for c in no_tail["result"]["pieces"]} | {int(o) for o in no_tail["result"]["not_kept"]}
    assert rebuilt == {c["ord"] for c in by_tree["pieces"]} and no_tail["result"]["not_kept"] == {}
    assert client.get(f"/v1/runs/{run_id}/artifacts").json() == kept
    assert client.get(f"/v1/runs/{run_id}/nodes").json() == pieces


def test_a_worker_reload_is_asked_only_when_the_worker_runs_older_code(client):
    asked = client.post("/v1/stand/worker/reload").json()
    assert asked["requested"] is False and asked["because"] == "no worker seen"
    with Session() as session:
        session.execute(text("INSERT INTO workers (host, code) VALUES ('w', :code)"),
                        {"code": code_version.tree_hash()})
        session.commit()
    assert client.post("/v1/stand/worker/reload").json()["requested"] is False
    assert not code_version.reload_requested("w")
    with Session() as session:
        session.execute(text("UPDATE workers SET code = 'older', seen_at = now()"))
        session.commit()
    assert client.post("/v1/stand/worker/reload").json()["requested"] is True
    assert code_version.reload_requested("w")
