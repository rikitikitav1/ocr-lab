import io
import tarfile
from datetime import timedelta

import pytest
import settings
import worker
from stages import assemble
from stages.structure import collect
from use_cases import runs as runs_use

from tests.fixtures import build, text_page
from tests.real_db import needs_db

pytestmark = needs_db


TEXT = "Body text of the chapter."


def _docling(page_no):
    item = {"self_ref": "#/texts/0", "parent": {"$ref": "#/body"}, "children": [], "content_layer": "body",
            "label": "text", "prov": [{"page_no": page_no, "bbox": {"l": 50, "t": 700, "r": 500, "b": 650}}],
            "orig": TEXT, "text": TEXT}
    return {"body": {"children": [{"$ref": "#/texts/0"}]}, "texts": [item], "groups": [], "tables": [],
            "pictures": [], "pages": {str(page_no): {"size": {"width": 595, "height": 842}}}}


def _mineru(page_idx):
    return {"pages": [{"page_idx": page_idx, "blocks": [
        {"index": 0, "type": "text", "bbox": [0.1, 0.2, 0.9, 0.3], "content": [{"type": "text", "content": TEXT}]}]}]}


# the engines answer with canned readings, which the read jobs keep as real artifacts
def engines(monkeypatch, broken_page: int | None = None):
    def read(engine, path, first, last, given, ceiling, build=None):
        if first == broken_page:
            raise ValueError("engine output unreadable")
        return _docling(first) if engine == "docling" else _mineru(first - 1)

    monkeypatch.setattr(assemble.reading, "read", read)


def _drain():
    worker.job_handlers.load_all()
    while worker.run_once("cpu") or worker.run_once("gpu"):
        pass


def test_a_run_assembles_every_chapter_and_writes_the_bundle(client, inbox, monkeypatch):
    from orm.catalogue import Run
    from orm.db import Session

    pages = [text_page("One", TEXT, bookmark="One"), text_page("Two", TEXT, bookmark="Two")]
    book = client.post("/v1/books", json={"file_paths": [str(build(inbox / "run.pdf", pages))], "then": []}).json()
    assert client.post(f"/v1/books/{book['id']}/runs", json={}).status_code == 400
    collect.collect(book["id"])
    engines(monkeypatch)
    started = client.post(f"/v1/books/{book['id']}/runs", json={})
    assert started.status_code == 202
    run_id = started.json()["run"]["id"]
    _drain()
    run = client.get(f"/v1/runs/{run_id}").json()
    assert run["status"] == "done" and run["pieces"] == {"done": 2}
    pieces = client.get(f"/v1/runs/{run_id}/nodes").json()
    assert [c["ord"] for c in pieces] == [1, 2] and all(c["engine"] == "assembled" for c in pieces)
    assert all(c["ord"] in c["nodes"] for c in pieces)
    assert {a["piece"] for a in client.get(f"/v1/runs/{run_id}/artifacts", params={"node": 2}).json()} == {2}
    bundle = settings.DATA_DIR / run["bundle_dir"]
    assert (bundle / "report.json").exists() and (bundle / "run.md").read_text().count(TEXT) == 2
    report = client.get(f"/v1/runs/{run_id}/report", params={"pieces": True}).json()
    assert report["numbers"]["pieces_done"] == 2 and [c["ord"] for c in report["pieces"]] == [1, 2]
    short = client.get(f"/v1/runs/{run_id}/report").json()
    assert "pieces" not in short and short["pieces_omitted"] == 2 and short["numbers"] == report["numbers"]
    brief = client.get(f"/v1/runs/{run_id}/nodes", params={"brief": True}).json()
    assert brief and all("passes" not in c["checks"] and "made_by" not in c["checks"] for c in brief)
    assert {a["name"] for a in client.get(f"/v1/runs/{run_id}/artifacts", params={"name": "piece.md"}).json()} \
        == {"piece.md"}
    assert report["numbers"]["reading_level"] == 0
    assert (bundle / "report.md").read_text().startswith("# ")
    kept = client.get(f"/v1/runs/{run_id}/artifacts", params={"node": 1, "stage": "assemble"}).json()
    md = next(a for a in kept if a["name"] == "piece.md")
    assert TEXT in client.get(f"/v1/runs/{run_id}/artifacts/{md['id']}").text
    pages = next(a for a in kept if a["name"] == "pages.json")
    picked = client.get(f"/v1/runs/{run_id}/artifacts/{pages['id']}").json()
    # the tail page comes from the next piece's reading, so piece 1 holds both pages its own read job left one out of
    assert sorted(picked) == ["1", "2"] and all(p["picked"] in ("docling", "mineru") for p in picked.values())
    assert client.get(f"/v1/runs/{run_id}/artifacts/{md['id'] + 10_000}").status_code == 404
    assert client.get(f"/v1/books/{book['id']}").json()["result_run_id"] == run_id
    answer = runs_use.book_bundle(book["id"])
    assert answer["numbers"]["pieces_done"] == 2 and answer["download"].endswith(f"/v1/runs/{run_id}/bundle")
    archive = tarfile.open(fileobj=io.BytesIO(client.get(f"/v1/books/{book['id']}/bundle").content))
    assert {"run.md", "report.json", "report.md"} <= set(archive.getnames())
    client.patch(f"/v1/books/{book['id']}/knobs", json={"set": {"structure.reading_level": 1}})
    deeper = client.post(f"/v1/books/{book['id']}/runs", json={}).json()["run"]["id"]
    with Session() as session:
        assert session.get(Run, deeper).reading_level == 1


def test_a_chapter_that_fails_for_good_sends_the_run_to_attention(client, inbox, monkeypatch):
    pages = [text_page("One", TEXT, bookmark="One"), text_page("Two", TEXT, bookmark="Two")]
    book = client.post("/v1/books", json={"file_paths": [str(build(inbox / "bad.pdf", pages))], "then": []}).json()
    collect.collect(book["id"])

    engines(monkeypatch, broken_page=2)
    monkeypatch.setattr(worker.job_specs, "attempts_for", lambda type: 1)
    started = client.post(f"/v1/books/{book['id']}/runs", json={}).json()
    run_id = started["run"]["id"]
    _drain()
    run = client.get(f"/v1/runs/{run_id}").json()
    assert run["status"] == "needs_attention" and run["pieces"] == {"done": 1, "failed": 1}
    failed = [c for c in client.get(f"/v1/runs/{run_id}/nodes").json() if c["status"] == "failed"]
    assert "unreadable" in failed[0]["errors"][0]["error"]
    waited = client.get(f"/v1/jobs/{started['job_id']}/wait", params={"timeout": 1}).json()
    assert [c["ord"] for c in waited["stopped_runs"][0]["failed_pieces"]] == [failed[0]["ord"]]
    assert "tree" not in waited and waited["counts"]["book_run"] == {"done": 1}
    assert waited["not_done"][0]["status"] == "error" and waited["not_done_total"] == len(waited["not_done"])
    full = client.get(f"/v1/jobs/{started['job_id']}/wait", params={"timeout": 1, "tree": True}).json()
    assert len(full["tree"]) == sum(sum(c.values()) for c in waited["counts"].values()) and "counts" not in full
    engines(monkeypatch)
    resumed = client.post(f"/v1/runs/{run_id}/resume").json()
    assert resumed["pieces_restarted"] == [failed[0]["ord"]]
    busy = client.post(f"/v1/runs/{run_id}/resume")
    assert busy.status_code == 409 and busy.json()["error"]["kind"] == "busy"
    assert f"wait_runs([{run_id}])" in busy.json()["error"]["message"]
    _drain()
    run = client.get(f"/v1/runs/{run_id}").json()
    assert run["status"] == "done" and run["pieces"] == {"done": 2}
    before = len(client.get(f"/v1/runs/{run_id}/artifacts", params={"node": 1, "stage": "assemble"}).json())
    assert client.post(f"/v1/runs/{run_id}/nodes/1/rerun", json={"overrides": {"x": 1}}).status_code == 400
    rerun = client.post(f"/v1/runs/{run_id}/nodes/1/rerun", json={}).json()
    assert rerun["unit"] == 1 and rerun["nodes_rerun"][0] == 1
    assert client.post(f"/v1/runs/{run_id}/nodes/99/rerun", json={}).status_code == 404
    _drain()
    assert client.get(f"/v1/runs/{run_id}").json()["status"] == "done"
    assert len(client.get(f"/v1/runs/{run_id}/artifacts", params={"node": 1, "stage": "assemble"}).json()) > before


def _failed(client, run_id: int, type: str) -> list[int]:
    return [j["id"] for j in client.get("/v1/jobs", params={"run_id": run_id, "type": type, "status": "error"}).json()]


@pytest.mark.parametrize("door", ["resume", "retry"])
def test_a_bundle_that_fails_for_good_sends_the_run_to_attention_and_either_door_writes_it(client, inbox, monkeypatch,
                                                                                          door):
    from stages import bundle

    pages = [text_page("One", TEXT, bookmark="One"), text_page("Two", TEXT, bookmark="Two")]
    book = client.post("/v1/books", json={"file_paths": [str(build(inbox / "nob.pdf", pages))], "then": []}).json()
    collect.collect(book["id"])
    engines(monkeypatch)
    monkeypatch.setattr(worker.job_specs, "attempts_for", lambda type: 1)
    write = bundle.write

    def broken(run_id):
        raise OSError("disk full")

    monkeypatch.setattr(bundle, "write", broken)
    run_id = client.post(f"/v1/books/{book['id']}/runs", json={}).json()["run"]["id"]
    _drain()
    run = client.get(f"/v1/runs/{run_id}").json()
    assert run["status"] == "needs_attention" and run["pieces"] == {"done": 2}
    assert [(e["type"], e["error"]) for e in run["errors"]] == [("book_metrics", "disk full")]
    monkeypatch.setattr(bundle, "write", write)
    if door == "resume":
        assert client.post(f"/v1/runs/{run_id}/resume").json()["pieces_restarted"] == []
    else:
        client.post("/v1/jobs/retry", json={"ids": _failed(client, run_id, "book_metrics")})
        assert client.get(f"/v1/runs/{run_id}").json()["stage"] == "metrics"
    _drain()
    run = client.get(f"/v1/runs/{run_id}").json()
    assert run["status"] == "done" and run["errors"] == []


# the retry door brings a failed piece back like a rerun does, and the run ends as it would after resume_run
def test_a_retried_read_and_a_retried_assembly_finish_the_run(client, inbox, monkeypatch):
    pages = [text_page("One", TEXT, bookmark="One"), text_page("Two", TEXT, bookmark="Two")]
    book = client.post("/v1/books", json={"file_paths": [str(build(inbox / "rty.pdf", pages))], "then": []}).json()
    collect.collect(book["id"])
    engines(monkeypatch, broken_page=2)
    monkeypatch.setattr(worker.job_specs, "attempts_for", lambda type: 1)
    run_id = client.post(f"/v1/books/{book['id']}/runs", json={}).json()["run"]["id"]
    _drain()
    assert client.get(f"/v1/runs/{run_id}").json()["status"] == "needs_attention"
    engines(monkeypatch)
    assembled = assemble.assemble

    def broken(book_id, ord, *args, **kwargs):
        raise ValueError("assembly broke")

    monkeypatch.setattr(assemble, "assemble", broken)
    client.post("/v1/jobs/retry", json={"ids": _failed(client, run_id, "read_piece")})
    run = client.get(f"/v1/runs/{run_id}").json()
    assert run["status"] == "running" and run["pieces"] == {"done": 1, "pending": 1}
    _drain()
    run = client.get(f"/v1/runs/{run_id}").json()
    assert run["status"] == "needs_attention" and run["pieces"] == {"done": 1, "failed": 1}
    monkeypatch.setattr(assemble, "assemble", assembled)
    client.post("/v1/jobs/retry", json={"ids": _failed(client, run_id, "assemble_piece")})
    _drain()
    run = client.get(f"/v1/runs/{run_id}").json()
    assert run["status"] == "done" and run["pieces"] == {"done": 2}
    assert client.get(f"/v1/books/{book['id']}").json()["result_run_id"] == run_id


def test_a_cancelled_run_stops_its_jobs_and_resumes_to_the_end(client, inbox, monkeypatch):
    pages = [text_page("One", TEXT, bookmark="One"), text_page("Two", TEXT, bookmark="Two")]
    book = client.post("/v1/books", json={"file_paths": [str(build(inbox / "stop.pdf", pages))], "then": []}).json()
    collect.collect(book["id"])
    engines(monkeypatch)
    run_id = client.post(f"/v1/books/{book['id']}/runs", json={}).json()["run"]["id"]
    worker.job_handlers.load_all()
    while worker.run_once("cpu"):
        pass
    cancelled = client.post(f"/v1/runs/{run_id}/cancel").json()
    assert cancelled["status"] == "cancelled" and len(cancelled["jobs_cancelled"]) == 4
    client.post(f"/v1/runs/{run_id}/resume")
    _drain()
    assert client.get(f"/v1/runs/{run_id}").json()["pieces"] == {"done": 2}


def test_a_worker_killed_mid_run_leaves_done_pieces_as_they_are_and_the_bundle_matches_an_uninterrupted_run(
        client, inbox, monkeypatch):
    import job_queue

    pages = [text_page(name, TEXT, bookmark=name) for name in ("One", "Two", "Three")]
    book = client.post("/v1/books", json={"file_paths": [str(build(inbox / "kill.pdf", pages))], "then": []}).json()
    collect.collect(book["id"])
    engines(monkeypatch)
    whole = client.post(f"/v1/books/{book['id']}/runs", json={}).json()["run"]["id"]
    _drain()
    killed = client.post(f"/v1/books/{book['id']}/runs", json={}).json()["run"]["id"]
    while not any(p["status"] == "done" for p in client.get(f"/v1/runs/{killed}/nodes").json()):
        assert worker.run_once("cpu") or worker.run_once("gpu")
    before = {a["id"]: a["sha256"] for a in client.get(f"/v1/runs/{killed}/artifacts").json()}
    # a worker that took a job and died: its host holds no lock, so the job goes back to the queue
    dead = job_queue.claim_next("cpu", None, "killed-worker") or job_queue.claim_next("gpu", None, "killed-worker")
    assert dead is not None and dead.id in job_queue.requeue_stale(["cpu", "gpu"], worker.HOST, starting=False)
    _drain()
    run = client.get(f"/v1/runs/{killed}").json()
    assert run["status"] == "done" and run["pieces"] == {"done": 3}
    after = {a["id"]: a["sha256"] for a in client.get(f"/v1/runs/{killed}/artifacts").json()}
    assert all(after.get(id) == sha for id, sha in before.items())
    bundles = [settings.DATA_DIR / client.get(f"/v1/runs/{r}").json()["bundle_dir"] for r in (whole, killed)]
    assert (bundles[0] / "kill.md").read_bytes() == (bundles[1] / "kill.md").read_bytes()


def test_a_piece_counts_as_changed_on_other_engine_builds_or_profile_and_a_new_run_leaves_the_last_one_s_files(
        client, inbox, monkeypatch):
    import profiles
    from orm.catalogue import Run
    from orm.db import Session
    from stages import piece_assembly, run_state

    pages = [text_page("One", TEXT, bookmark="One"), text_page("Two", TEXT, bookmark="Two")]
    book = client.post("/v1/books", json={"file_paths": [str(build(inbox / "reuse.pdf", pages))], "then": []}).json()
    collect.collect(book["id"])
    engines(monkeypatch)
    first = client.post(f"/v1/books/{book['id']}/runs", json={}).json()["run"]["id"]
    _drain()
    files = sorted((settings.DATA_DIR / "runs" / str(book["id"]) / str(first)).rglob("*"))
    shas = {f: f.read_bytes() for f in files if f.is_file()}
    with Session() as session:
        run = session.get(Run, first)
        assert not piece_assembly.piece_changed(session, run, 1)
        real = run_state.round_readings
        monkeypatch.setattr(run_state, "round_readings", lambda s, r, o: (real(s, r, o)[0], {"docling": {"base": "x"}}))
        assert piece_assembly.piece_changed(session, run, 1)
        monkeypatch.setattr(run_state, "round_readings", real)
        run.profile_id = profiles.derive(run.profile_id, pieces={1: {"assembly.tables_from": "docling"}})["id"]
        assert piece_assembly.piece_changed(session, run, 1)
    client.post(f"/v1/books/{book['id']}/runs", json={})
    _drain()
    assert all(f.read_bytes() == blob for f, blob in shas.items())


def test_a_write_that_fails_on_a_full_disk_leaves_no_row_and_no_file_so_the_stage_runs_again(stand, tmp_path,
                                                                                            monkeypatch):
    import errno

    import artifacts

    def full(path, data):
        raise OSError(errno.ENOSPC, "No space left on device")

    owner, inputs = artifacts.Owner(book_id=None), artifacts.Inputs({"stage": "probe", "n": 1})
    monkeypatch.setattr(artifacts, "atomic_write", full)
    with pytest.raises(OSError):
        artifacts.write(owner, tmp_path, "probe", "out.json", {"a": 1}, inputs)
    assert artifacts.find_done(owner, "probe", "out.json", inputs.key) is None
    assert not (settings.DATA_DIR / tmp_path / "probe" / "out.json").exists()


def test_a_run_was_made_from_its_latest_round_s_readings_not_an_older_round_s(client, inbox, monkeypatch):
    from orm.db import Session
    from orm.jobs import Job

    pages = [text_page("One", TEXT, bookmark="One"), text_page("Two", TEXT, bookmark="Two")]
    book = client.post("/v1/books", json={"file_paths": [str(build(inbox / "round.pdf", pages))], "then": []}).json()
    collect.collect(book["id"])
    engines(monkeypatch)
    run_id = client.post(f"/v1/books/{book['id']}/runs", json={}).json()["run"]["id"]
    _drain()
    own = next(a for a in client.get(f"/v1/runs/{run_id}/artifacts", params={"name": "piece.md"}).json())
    # a read job of a round before the one the piece was assembled from, naming another artifact
    with Session() as session:
        session.add(Job(type="read_piece", lane="gpu", run_id=run_id, status="done",
                        options={"ord": 1, "engine": "docling", "round": -1}, result={"readings": {"1-1": own["id"]}}))
        session.commit()
    used = {a["id"]: a for a in client.get(f"/v1/runs/{run_id}/artifacts", params={"used": True}).json()}
    assert not used[own["id"]].get("used") and any(a.get("used") and a["name"].startswith("reading.")
                                                    for a in used.values())


def test_a_run_reads_the_page_layout_it_started_on_and_a_failed_layout_is_the_job_s_failure(client, inbox, monkeypatch):
    from orm.catalogue import Artifact, Run
    from orm.db import Session
    from stages.layout import collect as layout_collect

    pages = [text_page("One", TEXT, bookmark="One"), text_page("Two", TEXT, bookmark="Two")]
    book = client.post("/v1/books", json={"file_paths": [str(build(inbox / "pin.pdf", pages))], "then": []}).json()
    collect.collect(book["id"])
    engines(monkeypatch)
    run_id = client.post(f"/v1/books/{book['id']}/runs", json={}).json()["run"]["id"]
    _drain()
    with Session() as session:
        pinned = session.get(Run, run_id).layout_version_id
    assert pinned == layout_collect.current(book["id"], layout_collect.PAGE).id
    model = next(a for a in client.get(f"/v1/runs/{run_id}/artifacts", params={"name": "model.json"}).json())
    # the piece's inputs name the layout, kept hashed like every input
    with Session() as session:
        assert "layout" in session.get(Artifact, model["id"]).meta["inputs"]

    def broken(*args, **kwargs):
        raise ValueError("layout unreadable")

    monkeypatch.setattr(layout_collect, "collect_page", broken)
    job = client.post(f"/v1/books/{book['id']}/recollect", json={"what": ["layout"]}).json()["job_id"]
    _drain()
    done = client.get(f"/v1/jobs/{job}").json()
    assert done["status"] != "done" and "layout unreadable" in str(done["waiting_because"] or done["error"])


def test_a_run_s_preset_follows_the_page_layout_it_pins_and_a_profile_derived_by_hand_stays(client, inbox, monkeypatch):
    import profiles
    from orm.catalogue import Profile, Run
    from orm.db import Session

    pages = [text_page("One", TEXT, bookmark="One"), text_page("Two", TEXT, bookmark="Two")]
    book = client.post("/v1/books", json={"file_paths": [str(build(inbox / "preset.pdf", pages))], "then": []}).json()
    collect.collect(book["id"])
    engines(monkeypatch)
    started = client.post(f"/v1/books/{book['id']}/runs", json={}).json()["run"]
    derived = profiles.derive(started["profile_id"], set={"assembly.tables_from": "docling"})["id"]
    by_hand = client.post(f"/v1/books/{book['id']}/runs", json={"profile_id": derived}).json()["run"]["id"]
    # the layout the run pins chooses another preset than the one current when the run was made
    monkeypatch.setattr(profiles, "chosen_preset", lambda book_id: ("technical", "monospace share"))
    _drain()
    with Session() as session:
        chosen = session.get(Profile, session.get(Run, started["id"]).profile_id)
        kept = session.get(Run, by_hand).profile_id
    assert chosen.preset == "technical" and kept == derived


def test_resume_keeps_a_done_piece_on_the_same_inputs_and_assembles_it_again_on_other_code(client, inbox,
                                                                                           monkeypatch):
    import code_version

    pages = [text_page("One", TEXT, bookmark="One"), text_page("Two", TEXT, bookmark="Two")]
    book = client.post("/v1/books", json={"file_paths": [str(build(inbox / "again.pdf", pages))], "then": []}).json()
    collect.collect(book["id"])
    engines(monkeypatch)
    run_id = client.post(f"/v1/books/{book['id']}/runs", json={}).json()["run"]["id"]
    _drain()
    # the code on disk is faked for the resume door only: the worker reloads itself when it sees the disk move
    real = code_version.tree_hash
    monkeypatch.setattr(code_version, "tree_hash", lambda root=None: code_version.LOADED)
    assert client.post(f"/v1/runs/{run_id}/resume").json()["pieces_restarted"] == []
    monkeypatch.setattr(code_version, "tree_hash", real)
    _drain()
    monkeypatch.setattr(code_version, "tree_hash", lambda root=None: "other code")
    ords = [p["ord"] for p in client.get(f"/v1/runs/{run_id}/nodes").json()]
    assert client.post(f"/v1/runs/{run_id}/resume").json()["pieces_restarted"] == ords
    monkeypatch.setattr(code_version, "tree_hash", real)
    _drain()
    assert client.get(f"/v1/runs/{run_id}").json()["pieces"] == {"done": 2}


def test_a_cancelled_chapter_leaves_the_run_in_attention_once_it_is_read(client, inbox, monkeypatch):
    import job_queue
    from orm.db import Session
    from orm.jobs import Job
    from sqlalchemy import select

    pages = [text_page("One", TEXT, bookmark="One"), text_page("Two", TEXT, bookmark="Two")]
    book = client.post("/v1/books", json={"file_paths": [str(build(inbox / "cut.pdf", pages))], "then": []}).json()
    collect.collect(book["id"])
    run_id = client.post(f"/v1/books/{book['id']}/runs", json={}).json()["run"]["id"]
    worker.job_handlers.load_all()
    while worker.run_once("cpu"):
        pass
    with Session() as session:
        reads = list(session.scalars(select(Job.id).where(Job.run_id == run_id, Job.type == "read_piece")))
    job_queue.cancel(reads)
    run = client.get(f"/v1/runs/{run_id}").json()
    assert run["status"] == "running" and run["pieces"] == {"pending": 2}, "reading a run must not settle it"
    worker.run_once("cpu")
    run = client.get(f"/v1/runs/{run_id}").json()
    assert run["status"] == "needs_attention" and run["pieces"] == {"failed": 2}


def test_a_chapter_read_by_both_engines_whose_assembly_was_never_queued_is_assembled_not_failed(client, inbox):
    from orm.db import Session
    from orm.jobs import Job
    from sqlalchemy import select, update

    pages = [text_page("One", TEXT, bookmark="One"), text_page("Two", TEXT, bookmark="Two")]
    book = client.post("/v1/books", json={"file_paths": [str(build(inbox / "lost.pdf", pages))], "then": []}).json()
    collect.collect(book["id"])
    run_id = client.post(f"/v1/books/{book['id']}/runs", json={}).json()["run"]["id"]
    worker.job_handlers.load_all()
    while worker.run_once("cpu"):
        pass
    with Session() as session:
        session.execute(update(Job).where(Job.run_id == run_id, Job.type == "read_piece").values(status="done"))
        session.commit()
    worker.run_once("cpu")
    run = client.get(f"/v1/runs/{run_id}").json()
    assert run["status"] == "running" and run["pieces"] == {"running": 2}
    with Session() as session:
        assert len(list(session.scalars(select(Job.id).where(Job.run_id == run_id,
                                                              Job.type == "assemble_piece")))) == 2


def test_a_run_on_a_stale_toc_collects_it_again_and_works_on_the_new_version(client, inbox, monkeypatch):
    from orm.catalogue import StructureVersion
    from orm.db import Session
    from sqlalchemy import update
    from stages.metadata import resolve

    pages = [text_page("One", TEXT, bookmark="One"), text_page("Two", TEXT, bookmark="Two")]
    book = client.post("/v1/books", json={"file_paths": [str(build(inbox / "old.pdf", pages))], "then": []}).json()
    old = collect.collect(book["id"])
    monkeypatch.setattr(resolve, "stale", lambda book_id: False)
    with Session() as session:
        session.execute(update(StructureVersion).where(StructureVersion.id == old)
                        .values(input_hash="made by older code"))
        session.commit()
    engines(monkeypatch)
    later = worker.job_queue.reschedule
    monkeypatch.setattr(worker.job_queue, "reschedule", lambda id, delay, because, **kw:
                        later(id, timedelta(0), because, **kw))
    run_id = client.post(f"/v1/books/{book['id']}/runs", json={}).json()["run"]["id"]
    worker.job_handlers.load_all()
    # both lanes in turn: the deferred run goes back on its lane while the structure it waits for is on the other
    for _ in range(100):
        if not (worker.run_once("gpu") | worker.run_once("cpu")):
            break
    run = client.get(f"/v1/runs/{run_id}").json()
    assert run["status"] == "done" and run["structure_version_id"] != old


def test_a_run_whose_toc_collect_fails_for_good_stops_in_attention_instead_of_collecting_again(client, inbox,
                                                                                                 monkeypatch):
    from orm.catalogue import StructureVersion
    from orm.db import Session
    from orm.jobs import Job
    from sqlalchemy import select, update
    from stages.metadata import resolve

    pages = [text_page("One", TEXT, bookmark="One"), text_page("Two", TEXT, bookmark="Two")]
    book = client.post("/v1/books", json={"file_paths": [str(build(inbox / "nit.pdf", pages))], "then": []}).json()
    old = collect.collect(book["id"])
    monkeypatch.setattr(resolve, "stale", lambda book_id: False)
    with Session() as session:
        session.execute(update(StructureVersion).where(StructureVersion.id == old)
                        .values(input_hash="made by older code"))
        session.commit()

    def unreadable(book_id, job_id=None, force=False):
        raise ValueError("contents unreadable")

    monkeypatch.setattr(collect, "collect", unreadable)
    monkeypatch.setattr(worker.job_specs, "attempts_for", lambda type: 1)
    later = worker.job_queue.reschedule
    monkeypatch.setattr(worker.job_queue, "reschedule", lambda id, delay, because, **kw:
                        later(id, timedelta(0), because, **kw))
    run_id = client.post(f"/v1/books/{book['id']}/runs", json={}).json()["run"]["id"]
    worker.job_handlers.load_all()
    for _ in range(100):
        if not (worker.run_once("gpu") | worker.run_once("cpu")):
            break
    run = client.get(f"/v1/runs/{run_id}").json()
    assert run["status"] == "needs_attention" and "contents unreadable" in run["errors"][0]["error"]
    with Session() as session:
        assert len(list(session.scalars(select(Job.id).where(Job.book_id == book["id"], Job.type == "structure")))) == 1


def test_a_rerun_chapter_whose_new_reads_are_cancelled_fails_instead_of_hanging_on_the_last_round(client, inbox,
                                                                                                    monkeypatch):
    import job_queue
    from orm.db import Session
    from orm.jobs import Job
    from sqlalchemy import select

    pages = [text_page("One", TEXT, bookmark="One"), text_page("Two", TEXT, bookmark="Two")]
    book = client.post("/v1/books", json={"file_paths": [str(build(inbox / "again.pdf", pages))], "then": []}).json()
    collect.collect(book["id"])
    engines(monkeypatch)
    run_id = client.post(f"/v1/books/{book['id']}/runs", json={}).json()["run"]["id"]
    _drain()
    assert client.post(f"/v1/runs/{run_id}/nodes/1/rerun", json={}).status_code == 202
    with Session() as session:
        fresh = list(session.scalars(select(Job.id).where(Job.run_id == run_id, Job.type == "read_piece",
                                                          Job.status == "new")))
    assert len(fresh) == 2
    with Session() as session:
        start = session.scalar(select(Job.id).where(Job.run_id == run_id, Job.type == "book_run"))
        assert {j["id"] for j in client.get(f"/v1/jobs/{start}").json()["tree"]} >= set(fresh)
    job_queue.cancel(fresh)
    worker.run_once("cpu")
    run = client.get(f"/v1/runs/{run_id}").json()
    assert run["status"] == "needs_attention" and run["pieces"] == {"done": 1, "failed": 1}


def test_a_run_whose_start_waits_past_its_limit_stops_in_attention(client, inbox, monkeypatch):
    from job_handlers import Deferred
    from job_handlers import run as run_handlers

    pages = [text_page("One", TEXT, bookmark="One"), text_page("Two", TEXT, bookmark="Two")]
    book = client.post("/v1/books", json={"file_paths": [str(build(inbox / "wait.pdf", pages))], "then": []}).json()
    collect.collect(book["id"])
    run_id = client.post(f"/v1/books/{book['id']}/runs", json={}).json()["run"]["id"]

    def stale(session, run):
        raise Deferred("waiting for fresh structure", delay_seconds=worker.MAX_DEFERRED_SECONDS + 1)

    monkeypatch.setattr(run_handlers, "_fresh_versions", stale)
    worker.job_handlers.load_all()
    while worker.run_once("cpu"):
        pass
    run = client.get(f"/v1/runs/{run_id}").json()
    assert run["status"] == "needs_attention" and [e["type"] for e in run["errors"]] == ["book_run"]
    refused = client.post(f"/v1/runs/{run_id}/resume")
    assert refused.status_code == 400 and "has no pieces" in refused.json()["error"]["message"]
    _drain()
    assert client.get(f"/v1/runs/{run_id}").json()["status"] == "needs_attention"
    assert client.get(f"/v1/books/{book['id']}").json()["result_run_id"] is None


def test_a_rerun_chapter_records_the_code_that_made_it_and_the_report_shows_the_mix(client, inbox, monkeypatch):
    import code_version

    pages = [text_page("One", TEXT, bookmark="One"), text_page("Two", TEXT, bookmark="Two")]
    book = client.post("/v1/books", json={"file_paths": [str(build(inbox / "mix.pdf", pages))], "then": []}).json()
    collect.collect(book["id"])
    engines(monkeypatch)
    run_id = client.post(f"/v1/books/{book['id']}/runs", json={}).json()["run"]["id"]
    _drain()
    monkeypatch.setattr(code_version, "LOADED", "newer")
    monkeypatch.setattr(code_version, "differs_from_disk", lambda: False)
    client.post(f"/v1/runs/{run_id}/nodes/2/rerun", json={})
    _drain()
    made = client.get(f"/v1/runs/{run_id}/report").json()["run"]["made_by"]
    assert sorted((m["code"] == "newer", m["pieces"]) for m in made) == [(False, [1]), (True, [2])]


def test_a_new_toc_version_clears_the_result_a_run_on_the_old_one_held(client, inbox, monkeypatch):
    pages = [text_page("One", TEXT, bookmark="One"), text_page("Two", TEXT, bookmark="Two")]
    book = client.post("/v1/books", json={"file_paths": [str(build(inbox / "toc.pdf", pages))], "then": []}).json()
    collect.collect(book["id"])
    engines(monkeypatch)
    run_id = client.post(f"/v1/books/{book['id']}/runs", json={}).json()["run"]["id"]
    _drain()
    assert client.get(f"/v1/books/{book['id']}").json()["result_run_id"] == run_id
    collect.collect(book["id"], force=True)
    assert client.get(f"/v1/books/{book['id']}").json()["result_run_id"] is None
    assert client.get(f"/v1/books/{book['id']}/bundle").status_code == 404


def _metadata_in(book_id: int, languages: list[str]) -> int:
    from orm.catalogue import MetadataField, MetadataVersion
    from orm.db import Session
    from stages import versions

    with Session() as session:
        versions.lock_book(session, book_id)
        version = versions.new(session, MetadataVersion, book_id, f"languages {languages}", None)
        session.add(MetadataField(metadata_version_id=version.id, name="languages", value=languages, source="manual",
                                  confidence=1.0, attempts=[]))
        session.commit()
        return version.id


def test_a_run_reads_and_reports_the_languages_of_the_metadata_it_pinned_not_of_a_newer_version(client, inbox,
                                                                                                 monkeypatch):
    from stages.metadata import resolve

    pages = [text_page("One", TEXT, bookmark="One"), text_page("Two", TEXT, bookmark="Two")]
    book = client.post("/v1/books", json={"file_paths": [str(build(inbox / "lang.pdf", pages))], "then": []}).json()
    collect.collect(book["id"])
    pinned = _metadata_in(book["id"], ["de"])
    monkeypatch.setattr(resolve, "stale", lambda book_id: False)
    engines(monkeypatch)
    run_id = client.post(f"/v1/books/{book['id']}/runs", json={}).json()["run"]["id"]
    _drain()
    _metadata_in(book["id"], ["ru"])
    assert client.post(f"/v1/runs/{run_id}/nodes/2/rerun", json={}).status_code == 202
    _drain()
    report = client.get(f"/v1/runs/{run_id}/report").json()
    assert report["metadata"]["metadata_version"] == pinned
    assert report["languages"]["book"] == ["de"]
    assert [(m["languages"], m["pieces"]) for m in report["run"]["made_by"]] == [(["de"], [1, 2])]


def _book(client, inbox, name: str, with_structure: bool = True) -> int:
    pages = [text_page("One", TEXT, bookmark="One"), text_page("Two", TEXT, bookmark="Two")]
    book = client.post("/v1/books", json={"file_paths": [str(build(inbox / name, pages))], "then": []}).json()
    if with_structure:
        collect.collect(book["id"])
    return book["id"]


def _started(client, *book_ids) -> list[int]:
    started = client.post("/v1/runs", json={"book_ids": list(book_ids)})
    assert started.status_code == 202
    return [r["run_id"] for r in started.json()["runs"]]


def test_runs_start_in_bulk_show_reads_per_engine_and_are_waited_for_and_listed(client, inbox, monkeypatch):
    ready, bare = _book(client, inbox, "bulk1.pdf"), _book(client, inbox, "bulk2.pdf", with_structure=False)
    refused = client.post("/v1/runs", json={"book_ids": [ready, bare]})
    assert refused.status_code == 400 and f"book {bare}" in refused.json()["error"]["message"]
    assert client.get("/v1/runs", params={"book_id": ready}).json() == []
    collect.collect(bare)
    engines(monkeypatch)
    run_ids = _started(client, ready, bare)
    worker.job_handlers.load_all()
    while worker.run_once("cpu"):
        pass
    reading = client.get(f"/v1/runs/{run_ids[0]}").json()
    assert reading["reads"] == {"docling": {"total": 2, "new": 2}, "mineru": {"total": 2, "new": 2}}
    waited = client.get("/v1/runs/wait", params={"ids": run_ids, "timeout": 0.2}).json()
    assert waited["timeout"] and [r["status"] for r in waited["runs"]] == ["running", "running"]
    _drain()
    waited = client.get("/v1/runs/wait", params={"ids": run_ids, "timeout": 5}).json()
    assert waited["settled"] and [r["pieces"] for r in waited["runs"]] == [{"done": 2}, {"done": 2}]
    assert client.get(f"/v1/runs/{run_ids[0]}").json()["reads"]["mineru"] == {"total": 2, "done": 2}
    listed = client.get("/v1/runs", params={"ids": run_ids}).json()
    assert [r["id"] for r in listed] == sorted(run_ids, reverse=True)
    assert all(r["status"] == "done" and r["pages"] == 2 and "total" in r["seconds_per_page"] for r in listed)
    assert client.get("/v1/runs/wait", params={"ids": [run_ids[0] + 10_000]}).status_code == 404


def test_runs_cancel_in_bulk_leave_finished_ones_and_a_dry_run_stops_nothing(client, inbox, monkeypatch):
    engines(monkeypatch)
    finished = _started(client, _book(client, inbox, "c1.pdf"))[0]
    _drain()
    going = _started(client, _book(client, inbox, "c2.pdf"))[0]
    worker.job_handlers.load_all()
    while worker.run_once("cpu"):
        pass
    dry = client.post("/v1/runs/cancel", json={"ids": [finished, going], "dry_run": True}).json()
    assert dry["skipped"] == [finished] and len(dry["runs"][0]["jobs"]) == 4
    assert client.get(f"/v1/runs/{going}").json()["status"] == "running"
    done = client.post("/v1/runs/cancel", json={"ids": [finished, going]}).json()
    assert done["runs"] == [{"run_id": going, "jobs": dry["runs"][0]["jobs"]}]
    statuses = {r["id"]: r["status"] for r in client.get("/v1/runs", params={"ids": [finished, going]}).json()}
    assert statuses == {finished: "done", going: "cancelled"}
    assert client.post("/v1/runs/cancel", json={"ids": [going + 10_000]}).status_code == 404


def test_two_runs_of_a_book_compare_by_chapter_and_only_the_moved_chapters_are_listed(client, inbox, monkeypatch):
    from orm.catalogue import Piece
    from orm.db import Session

    engines(monkeypatch)
    book = _book(client, inbox, "cmp.pdf")
    first = _started(client, book)[0]
    _drain()
    second = _started(client, book)[0]
    _drain()
    same = client.get("/v1/runs/compare", params={"a": first, "b": second}).json()
    assert same["same_structure"] and same["pieces_moved"] == [] and same["numbers"]["pieces_done"] == [2, 2]
    with Session() as session:
        piece = session.get(Piece, (second, 2))
        piece.checks = {**piece.checks, "lost_words": piece.checks["lost_words"] + 7}
        session.commit()
    moved = client.get("/v1/runs/compare", params={"a": first, "b": second, "keys": ["lost_words"]}).json()
    assert [(c["ord"], c["lost_words"][1] - c["lost_words"][0]) for c in moved["pieces_moved"]] == [([2, 2], 7)]
    assert moved["totals"]["lost_words"][1] - moved["totals"]["lost_words"][0] == 7
    other = _started(client, _book(client, inbox, "cmp2.pdf"))[0]
    assert client.get("/v1/runs/compare", params={"a": first, "b": other}).status_code == 400


def test_a_submission_asking_for_a_run_gets_one_after_its_toc_and_one_without_does_not(client, inbox, monkeypatch):
    pages = [text_page("One", TEXT, bookmark="One"), text_page("Two", TEXT, bookmark="Two")]
    engines(monkeypatch)
    book = client.post("/v1/books", json={"file_paths": [str(build(inbox / "auto.pdf", pages))],
                                          "then": ["structure", "run"]}).json()
    _drain()
    runs = client.get("/v1/runs", params={"book_id": book["id"]}).json()
    assert [r["status"] for r in runs] == ["done"]
    waited = client.get(f"/v1/jobs/{book['job_id']}/wait", params={"timeout": 1, "tree": True}).json()
    assert waited["finished"] and "book_run" in {j["type"] for j in waited["tree"]}
    eta = client.get(f"/v1/books/{book['id']}").json()["eta"]
    seconds = eta["run_seconds"]
    assert eta["cost_runs"]["text"] == 0 or seconds["min"] <= seconds["median"] <= seconds["max"]
    plain = client.post("/v1/books", json={"file_paths": [str(build(inbox / "only.pdf", pages))],
                                           "then": ["structure"]}).json()
    _drain()
    assert client.get("/v1/runs", params={"book_id": plain["id"]}).json() == []


def test_a_piece_is_assembled_only_once_the_piece_after_it_is_read(client, inbox):
    from orm.db import Session
    from orm.jobs import Job
    from sqlalchemy import select, update
    from stages import run_state

    pages = [text_page("One", TEXT, bookmark="One"), text_page("Two", TEXT, bookmark="Two")]
    book = client.post("/v1/books", json={"file_paths": [str(build(inbox / "wait.pdf", pages))], "then": []}).json()
    collect.collect(book["id"])
    run_id = client.post(f"/v1/books/{book['id']}/runs", json={}).json()["run"]["id"]
    worker.job_handlers.load_all()
    while worker.run_once("cpu"):
        pass

    def read(ord):
        with Session() as session:
            session.execute(update(Job).where(Job.run_id == run_id, Job.type == "read_piece",
                                              Job.options["ord"].astext == str(ord)).values(status="done"))
            session.commit()
        run_state.assemble_when_read(run_id, ord)
        with Session() as session:
            return sorted(j.options["ord"] for j in session.scalars(select(Job).where(
                Job.run_id == run_id, Job.type == "assemble_piece")))

    assert read(1) == []
    assert read(2) == [1, 2]


def test_a_bulk_start_hangs_its_runs_under_one_batch_that_one_wait_covers(client, inbox, monkeypatch):
    first, second = _book(client, inbox, "batch1.pdf"), _book(client, inbox, "batch2.pdf")
    engines(monkeypatch)
    started = client.post("/v1/runs", json={"book_ids": [first, second]}).json()
    batch = started["batch_job_id"]
    pending = client.get(f"/v1/jobs/{batch}/wait", params={"timeout": 0.2}).json()
    assert pending["finished"] is False and pending["counts"]["book_run"] == {"new": 2}
    _drain()
    done = client.get(f"/v1/jobs/{batch}/wait", params={"timeout": 1}).json()
    assert done["finished"] and done["counts"]["book_run"] == {"done": 2} and done["counts"]["batch"] == {"done": 1}
    again = client.post("/v1/books/recollect", json={"ids": [first, second], "what": ["structure"]}).json()
    heads = client.get("/v1/jobs", params={"parent_id": again["batch_job_id"]}).json()
    assert sorted(j["id"] for j in heads) == sorted(again["jobs"].values())
    _drain()
    assert client.get(f"/v1/jobs/{again['batch_job_id']}/wait", params={"timeout": 1}).json()["finished"]


def test_many_pairs_compare_at_once_by_numbers_pieces_and_the_bundle_text(client, inbox, monkeypatch):
    book = _book(client, inbox, "pairs.pdf")
    engines(monkeypatch)
    first = client.post(f"/v1/books/{book}/runs", json={}).json()["run"]["id"]
    _drain()
    second = client.post(f"/v1/books/{book}/runs", json={}).json()["run"]["id"]
    _drain()
    got = client.post("/v1/runs/compare", json={"pairs": [[first, second]]}).json()
    row = got["rows"][0]
    assert got["pairs"] == 1 and row["book_id"] == book and row["bundle"]["same"] is True
    assert row["bundle"]["lines_changed"] == 0 and row["pieces_moved"] == 0
    assert client.post("/v1/runs/compare", json={"pairs": [[first]]}).status_code == 400


def test_a_page_of_a_run_names_its_pieces_their_cut_its_blocks_and_its_words(client, inbox, monkeypatch):
    book = _book(client, inbox, "page.pdf")
    engines(monkeypatch)
    run_id = client.post(f"/v1/books/{book}/runs", json={}).json()["run"]["id"]
    _drain()
    got = client.get(f"/v1/runs/{run_id}/pages/1").json()
    assert got["page"] == 1 and [p["ord"] for p in got["pieces"]] and got["pieces"][0]["assembled"]
    blocks = [b for p in got["pieces"] for b in p["blocks"]]
    assert blocks and all({"type", "engine", "box", "text"} <= set(b) for b in blocks)
    assert got["layer_words"] > 0 and got["lost"] <= got["layer_words"]
    assert client.get(f"/v1/runs/{run_id}/pages/999").status_code == 404
