import pytest
import settings
from stages.metadata import resolve
from stages.metadata.candidates import SourceResult

from tests.fixtures import build, text_page
from tests.real_db import needs_db

pytestmark = needs_db


@pytest.fixture
def inbox(stand):
    folder = settings.DATA_DIR / "inbox"
    folder.mkdir(parents=True)
    return folder


def _fake_sources(title, series=None, volume=None):
    def gather(book_id, manual):
        r = SourceResult("model", covers=("title", "series", "volume"))
        r.add("title", title, 0.9)
        r.add("series", series, 0.8)
        r.add("volume", volume, 0.8)
        return [manual, r]
    return gather


def test_submit_twice_returns_the_same_book(client, inbox):
    pdf = build(inbox / "x.pdf", [text_page("Hello")])
    first = client.post("/v1/books", json={"file_paths": [str(pdf)]})
    second = client.post("/v1/books", json={"file_paths": [str(pdf)]})
    assert first.json()["created"] is True and second.json()["created"] is False
    assert first.json()["id"] == second.json()["id"]
    assert (first.status_code, second.status_code) == (201, 200)
    assert client.post(f"/v1/books/{first.json()['id']}/recollect", json={}).status_code == 202
    jobs = client.get("/v1/jobs", params={"book_id": first.json()["id"]}).json()
    assert jobs and {j["book_id"] for j in jobs} == {first.json()["id"]}
    assert "intake" in client.get(f"/v1/books/{first.json()['id']}").json()["stages"]
    assert "gpu_holders" in client.get("/v1/queue").json()
    assert client.get(f"/v1/books/{first.json()['id']}").json()["stale"] == {"metadata": False, "toc": False}


def test_paths_outside_shelf_are_refused(client, stand, tmp_path):
    outside = build(tmp_path / "elsewhere.pdf", [text_page("x")])
    assert client.post("/v1/books", json={"file_paths": [str(outside)]}).status_code == 400


def test_manual_metadata_makes_a_new_version(client, inbox, monkeypatch):
    monkeypatch.setattr(resolve, "gather", _fake_sources("Found title"))
    book = client.post("/v1/books", json={"file_paths": [str(build(inbox / "m.pdf", [text_page("x")]))]}).json()
    resolve.collect(book["id"])
    changed = client.patch(f"/v1/books/{book['id']}/metadata/title", json={"value": "Hand title"}).json()
    assert changed["value"] == "Hand title" and changed["source"] == "manual" and changed["version"] == 2
    assert any(a.get("values") == ["Found title"] for a in changed["attempts"])
    assert client.patch(f"/v1/books/{book['id']}/metadata/nope", json={"value": 1}).status_code == 400


def test_series_filter_sorts_by_volume(client, inbox, monkeypatch):
    ids = []
    for volume in ("10", "IX", "2"):
        monkeypatch.setattr(resolve, "gather", _fake_sources(f"Vol {volume}", "Saga", volume))
        book = client.post("/v1/books", json={"file_paths": [str(build(inbox / f"v{volume}.pdf",
                                                                           [text_page(volume)]))]}).json()
        resolve.collect(book["id"])
        ids.append(book["id"])
    listed = client.get("/v1/books", params={"series": "saga"}).json()
    assert [b["id"] for b in listed] == [ids[2], ids[1], ids[0]]
    assert listed[0]["title"] == "Vol 2" and "files" not in listed[0] and listed[0]["last_run"] is None
    assert [b["id"] for b in client.get("/v1/books", params={"series": "saga", "offset": 1, "limit": 1}).json()] == [
        ids[1]]
    full = client.get("/v1/books", params={"series": "saga", "brief": False}).json()
    assert full[0]["files"][0]["path"].startswith("files/") and full[0]["metadata"]["fields"]["volume"]["value"] == "2"


def test_volume_order_reads_roman_numbers_and_puts_words_last():
    from use_cases.books import volume_order

    assert sorted(["10", "Supplement", "IX", "2", "3a", None], key=volume_order) == [
        "2", "3a", "IX", "10", None, "Supplement"]


def test_a_shelf_snapshot_names_the_books_whose_toc_or_metadata_moved(client, inbox, monkeypatch):
    from stages.toc import collect

    monkeypatch.setattr(resolve, "gather", _fake_sources("Found title"))
    path = build(inbox / "h.pdf", [text_page("One", bookmark="One"), text_page("Two", bookmark="Two")])
    book = client.post("/v1/books", json={"file_paths": [str(path)], "then": []}).json()
    still = client.post("/v1/books", json={"file_paths": [str(build(inbox / "i.pdf", [text_page("x")]))],
                                           "then": []}).json()
    collect.collect(book["id"])
    resolve.collect(book["id"])
    assert client.post("/v1/shelf/snapshots", json={"book_ids": [999999]}).status_code == 404
    taken = client.post("/v1/shelf/snapshots", json={}).json()
    assert taken["books"] >= 2
    assert client.get(f"/v1/shelf/snapshots/{taken['id']}/changes").json()["moved"] == []
    collect.collect(book["id"], force=True)
    unchanged = client.get(f"/v1/shelf/snapshots/{taken['id']}/changes").json()
    assert unchanged["moved"] == [] and unchanged["with_new_versions"] == 1
    entries = client.get(f"/v1/books/{book['id']}/toc").json()["entries"][:-1]
    rows = [{k: e[k] for k in ("ord", "title", "level", "level_source", "first_page", "last_page", "kind", "votes")}
            for e in entries]
    collect.write_version(book["id"], collect.inputs(book["id"]), rows, None, {"chosen": "printed_contents"})
    client.patch(f"/v1/books/{book['id']}/metadata/title", json={"value": "Hand title"})
    changes = client.get(f"/v1/shelf/snapshots/{taken['id']}/changes",
                         params={"book_ids": [book["id"], still["id"]]}).json()
    assert changes["books"] == 2 and [m["book_id"] for m in changes["moved"]] == [book["id"]]
    toc, meta = changes["moved"][0]["toc"], changes["moved"][0]["metadata"]
    assert toc["base"] == ["bookmarks", "printed_contents"] and [r["title"] for r in toc["removed"]] == ["Two"]
    assert meta["fields"]["title"]["after"] == {"value": "Hand title", "source": "manual"}
    assert client.get("/v1/shelf/snapshots/999999/changes").status_code == 404


def test_toc_is_collected_alone_and_read_through_the_door(client, inbox):
    import job_queue

    path = build(inbox / "r.pdf", [text_page("One", bookmark="One"), text_page("Two", bookmark="Two")])
    book = client.post("/v1/books", json={"file_paths": [str(path)], "then": ["toc"]}).json()
    assert client.get(f"/v1/books/{book['id']}/toc").status_code == 404
    job = client.post(f"/v1/books/{book['id']}/recollect", json={"what": ["toc"]}).json()["job_id"]
    assert job_queue.get(job).type == "toc"
    from stages.toc import collect

    collect.collect(book["id"])
    toc = client.get(f"/v1/books/{book['id']}/toc").json()
    assert [(e["title"], e["first_page"], e["last_page"]) for e in toc["entries"]] == [("One", 1, 1), ("Two", 2, 2)]
    assert toc["chosen"] == "bookmarks"
    assert client.get(f"/v1/books/{book['id']}").json()["toc"] == {"version": toc["version"], "base": "bookmarks"}
    assert client.get(f"/v1/books/{book['id']}/toc", params={"source": "bookmarks"}).json()["chosen"] == "bookmarks"
    assert client.get(f"/v1/books/{book['id']}/toc", params={"source": "nope"}).status_code == 404


def test_knobs_at_submission_and_later(client, inbox):
    pdf = build(inbox / "k.pdf", [text_page(str(i)) for i in range(12)])
    book = client.post("/v1/books", json={"file_paths": [str(pdf)],
                                          "knobs": {"toc.contents_pages": [[3, 4]],
                                                    "metadata.title_pages.head": 5}}).json()
    assert book["knobs"] == {"toc.contents_pages": [[3, 4]], "metadata.title_pages.head": 5}
    changed = client.patch(f"/v1/books/{book['id']}/knobs",
                           json={"set": {"metadata.title_pages.tail": 2}, "unset": ["metadata.title_pages.head"]})
    assert changed.json()["effective"]["metadata.title_pages.head"] == 20
    assert changed.json()["effective"]["metadata.title_pages.tail"] == 2


def test_bad_knobs_are_refused(client, inbox):
    pdf = build(inbox / "b.pdf", [text_page("1"), text_page("2")])
    assert client.post("/v1/books", json={"file_paths": [str(pdf)], "knobs": {"nope": 1}}).status_code == 400
    out_of_range = {"toc.contents_pages": [[1, 50]]}
    assert client.post("/v1/books", json={"file_paths": [str(pdf)], "knobs": out_of_range}).status_code == 400
    not_a_switch = {"toc.from_headings": "yes"}
    assert client.post("/v1/books", json={"file_paths": [str(pdf)], "knobs": not_a_switch}).status_code == 400
    run_without_toc = client.post("/v1/books", json={"file_paths": [str(pdf)], "then": ["metadata", "run"]})
    assert run_without_toc.status_code == 400 and "add toc" in run_without_toc.json()["error"]["message"]


def test_given_contents_pages_mark_printed_contents(stand, inbox):
    from stages import intake

    pdf = build(inbox / "c.pdf", [text_page(str(i)) for i in range(6)])
    book, _ = intake.register([(pdf, "c.pdf")], {"toc.contents_pages": [[2, 3]]})
    probed = intake.probe(book)
    assert probed["has_printed_contents"] is True
    assert probed["toc_sources"]["contents_pages_given"] == [[2, 3]]


def test_original_title_is_optional_and_not_missing(client, inbox, monkeypatch):
    monkeypatch.setattr(resolve, "gather", _fake_sources("A title"))
    book = client.post("/v1/books", json={"file_paths": [str(build(inbox / "o.pdf", [text_page("x")]))]}).json()
    resolve.collect(book["id"])
    fields = {f["name"]: f for f in client.get(f"/v1/books/{book['id']}/metadata").json()}
    assert fields["original_title"]["optional"] is True and fields["isbn"]["optional"] is False
    record = client.get(f"/v1/books/{book['id']}").json()["metadata"]
    assert "original_title" not in record["missing"] and "isbn" in record["not_found"]
    assert "authors" in record["missing"]
    coverage = client.get("/v1/metadata/coverage").json()
    assert coverage["fields"]["authors"]["class"] == "required"
    assert book["id"] in {int(k) for k in coverage["books_missing_required"]}


def test_recollect_defaults_and_refusals(client, inbox, monkeypatch):
    monkeypatch.setattr(resolve, "gather", _fake_sources("T"))
    book = client.post("/v1/books", json={"file_paths": [str(build(inbox / "d.pdf", [text_page("x")]))]}).json()
    assert "job_id" in client.post(f"/v1/books/{book['id']}/recollect", json={}).json()
    assert client.post(f"/v1/books/{book['id']}/recollect", json={"what": ["foo"]}).status_code == 400
    import job_queue
    before = len(job_queue.live_ids())
    assert client.post("/v1/books/recollect", json={"ids": [book["id"], 999999]}).status_code == 404
    assert len(job_queue.live_ids()) == before


def test_recollect_with_run_passes_it_down_the_chain_and_needs_the_toc(client, inbox):
    book = client.post("/v1/books", json={"file_paths": [str(build(inbox / "r.pdf", [text_page("x")]))],
                                          "then": []}).json()
    url = f"/v1/books/{book['id']}/recollect"
    assert client.post(url, json={"what": ["metadata"], "run": True}).status_code == 400

    def options(answer):
        return client.get(f"/v1/jobs/{answer.json()['job_id']}").json()["options"]

    assert options(client.post(url, json={"what": ["toc"], "run": True}))["run"] is True
    assert options(client.post(url, json={"what": ["metadata", "toc"], "run": True}))["run"] is True
    assert "run" in options(client.post(url, json={"what": ["intake"], "run": True}))["then"]
    assert options(client.post(url, json={"what": ["toc"]}))["run"] is False
    many = client.post("/v1/books/recollect", json={"ids": [book["id"]], "what": ["toc"], "run": True}).json()
    assert client.get(f"/v1/jobs/{many['jobs'][str(book['id'])]}").json()["options"]["run"] is True


def test_a_manual_edit_never_passes_for_a_collection(client, inbox, monkeypatch):
    from orm.catalogue import MetadataVersion
    from orm.db import Session
    from sqlalchemy import select

    monkeypatch.setattr(resolve, "gather", _fake_sources("Found"))
    book = client.post("/v1/books", json={"file_paths": [str(build(inbox / "e.pdf", [text_page("x")]))]}).json()
    resolve.collect(book["id"])
    client.patch(f"/v1/books/{book['id']}/metadata/title", json={"value": "Hand"})
    with Session() as session:
        current = session.scalar(select(MetadataVersion).where(MetadataVersion.book_id == book["id"],
                                                               MetadataVersion.current))
    assert current.input_hash.startswith(resolve.MANUAL_STAMP)
    resolve.collect(book["id"])
    fields = {f["name"]: f for f in client.get(f"/v1/books/{book['id']}/metadata").json()}
    assert fields["title"]["value"] == "Hand" and fields["title"]["version"] == 3


def test_toc_eval_scores_the_contents_against_bookmarks_switched_off(client, inbox):
    import job_queue
    from job_handlers import evaluation

    from tests.fixtures import FILLER

    pages = [{"lines": ["Contents", *[f"Chapter {n} Part number {n} . . . . . . . . . . {n + 1}" for n in (1, 2, 3)]]}]
    pages += [{"lines": [f"Chapter {n} Part number {n}", FILLER[:90]], "bookmark": f"Chapter {n} Part number {n}"}
              for n in (1, 2, 3)]
    book = client.post("/v1/books", json={"file_paths": [str(build(inbox / "e.pdf", pages))], "then": []}).json()
    from stages import intake

    intake.probe(book["id"])
    assert client.post("/v1/eval/toc", json={"set": "longdocbench"}).status_code == 400
    unknown = {"set": "bookmarks_off", "book_ids": [book["id"], 999999]}
    assert client.post("/v1/eval/toc", json=unknown).status_code == 404
    job = client.post("/v1/eval/toc", json={"set": "bookmarks_off", "book_ids": [book["id"]]}).json()["job_id"]
    result = evaluation.run_toc_eval({**job_queue.get(job).options, "_job_id": job})
    assert result["chapters"] == 3 and result["chapters_found"] == 3
    assert result["rows"][0]["source"] == "printed_contents"
    job_queue.complete(job, result=result)
    other = client.post("/v1/eval/toc", json={"set": "bookmarks_off", "book_ids": [book["id"]]}).json()["job_id"]
    compare = {"job_a": job, "job_b": other}
    assert client.get("/v1/eval/toc/compare", params=compare).status_code == 400
    worse = {**result, "chapters_found": 2, "rows": [{**result["rows"][0], "chapters_found": 2}],
             "books_with_missed_chapters": [{"book_id": book["id"], "missed": [{"title": "Chapter 2 Part number 2"}]}]}
    job_queue.complete(other, result=worse)
    same = client.get("/v1/eval/toc/compare", params={"job_a": job, "job_b": job}).json()
    assert same["moved"] == [] and same["unchanged"] == 1
    moved = client.get("/v1/eval/toc/compare", params=compare).json()
    assert moved["totals"]["chapters_found"] == {"a": 3, "b": 2, "delta": -1}
    assert [(m["book_id"], m["changed"]) for m in moved["moved"]] == [(book["id"], ["chapters_found", "missed"])]
    assert moved["moved"][0]["b"]["missed"] == ["Chapter 2 Part number 2"]


def test_every_tool_takes_its_use_case_arguments():
    import asyncio

    import server  # noqa: F401
    from mcp_tools import mcp

    tool = asyncio.run(mcp.get_tool("books"))
    assert {"series", "q", "limit", "offset", "brief"} <= set(tool.parameters["properties"])


def test_a_toc_version_without_its_evidence_is_collected_again(client, inbox):
    from orm.catalogue import Artifact
    from orm.db import Session
    from sqlalchemy import delete
    from stages.toc import collect

    path = build(inbox / "k.pdf", [text_page("One", bookmark="One"), text_page("Two", bookmark="Two")])
    book = client.post("/v1/books", json={"file_paths": [str(path)], "then": []}).json()
    first = collect.collect(book["id"])
    assert collect.collect(book["id"]) == first
    with Session() as session:
        session.execute(delete(Artifact).where(Artifact.toc_version_id == first))
        session.commit()
    assert client.get(f"/v1/books/{book['id']}/toc", params={"source": "bookmarks"}).status_code == 404
    assert collect.collect(book["id"]) != first


def test_a_scans_toc_goes_stale_when_the_mineru_build_changes(client, inbox, monkeypatch):
    from engines import converter
    from stages.toc import collect

    path = build(inbox / "s.pdf", [text_page("One"), text_page("Two")])
    book = client.post("/v1/books", json={"file_paths": [str(path)], "then": []}).json()
    monkeypatch.setattr(collect, "scanned", lambda book_id: True)
    monkeypatch.setattr(converter, "build", lambda name: {"base": "a"})
    first = collect.inputs(book["id"]).key
    monkeypatch.setattr(converter, "build", lambda name: {"base": "b"})
    assert collect.inputs(book["id"]).key != first


def test_metadata_collected_again_keeps_a_ready_book_ready(client, inbox, monkeypatch):
    from stages.toc import collect

    path = build(inbox / "st.pdf", [text_page("One", bookmark="One"), text_page("Two", bookmark="Two")])
    book = client.post("/v1/books", json={"file_paths": [str(path)], "then": []}).json()
    monkeypatch.setattr(resolve, "gather", _fake_sources("A title"))
    resolve.collect(book["id"])
    assert client.get(f"/v1/books/{book['id']}").json()["stage"] == "metadata"
    collect.collect(book["id"])
    resolve.collect(book["id"], force=True)
    assert client.get(f"/v1/books/{book['id']}").json()["stage"] == "ready"


def test_metadata_needing_the_card_hands_itself_to_the_gpu_lane(client, inbox, monkeypatch):
    import job_queue
    import worker
    from engines import card

    calls = []

    # a book an earlier test left in the module's database may be collected here too, so calls name their book
    def collect(book_id, job_id=None, force=False):
        calls.append((book_id, job_queue.running_lane.get()))
        if job_queue.running_lane.get() == "cpu":
            raise card.WrongLane("ollama is needed, and the card is taken only on the GPU lane")
        return 1

    monkeypatch.setattr(resolve, "collect", collect)
    book = client.post("/v1/books", json={"file_paths": [str(build(inbox / "g.pdf", [text_page("x")]))],
                                          "then": ["metadata"]}).json()
    worker.job_handlers.load_all()
    while worker.run_once("cpu") or worker.run_once("gpu"):
        pass
    jobs = {j["type"]: j for j in client.get("/v1/jobs", params={"book_id": book["id"]}).json()}
    assert jobs["metadata"]["lane"] == "cpu" and "metadata_gpu_job_id" in jobs["metadata"]["result"]
    assert jobs["metadata_gpu"]["status"] == "done" and [lane for b, lane in calls if b == book["id"]] == ["cpu", "gpu"]


def test_the_element_eval_takes_run_knobs_and_refuses_an_unknown_one(client):
    refused = client.post("/v1/eval/elements", json={"knobs": {"assembly.no_such_pass": True}})
    assert refused.status_code == 400 and "unknown run knob" in refused.json()["error"]["message"]
    job = client.post("/v1/eval/elements", json={"ids": ["x"], "knobs": {"assembly.code_union": True}}).json()
    assert client.get(f"/v1/jobs/{job['job_id']}").json()["options"]["knobs"] == {"assembly.code_union": True}
