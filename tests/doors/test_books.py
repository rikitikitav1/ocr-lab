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
        r = SourceResult("catalogue:labirint", covers=("title", "series"))
        r.add("title", title, 0.9)
        r.add("series", series, 0.8)
        r.add("volume", volume, 0.8)
        return [manual, r], None
    return gather


def test_submit_twice_returns_the_same_book(client, inbox):
    pdf = build(inbox / "x.pdf", [text_page("Hello")])
    first = client.post("/v1/books", json={"file_paths": [str(pdf)]})
    second = client.post("/v1/books", json={"file_paths": [str(pdf)]})
    assert first.json()["created"] is True and second.json()["created"] is False
    assert first.json()["id"] == second.json()["id"]


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
    for volume in ("2", "1"):
        monkeypatch.setattr(resolve, "gather", _fake_sources(f"Vol {volume}", "Saga", volume))
        book = client.post("/v1/books", json={"file_paths": [str(build(inbox / f"v{volume}.pdf",
                                                                           [text_page(volume)]))]}).json()
        resolve.collect(book["id"])
        ids.append(book["id"])
    listed = client.get("/v1/books", params={"series": "saga"}).json()
    assert [b["id"] for b in listed] == [ids[1], ids[0]]


def test_recollect_refuses_toc_until_that_stage_exists(client, inbox):
    book = client.post("/v1/books", json={"file_paths": [str(build(inbox / "r.pdf", [text_page("x")]))]}).json()
    assert client.post(f"/v1/books/{book['id']}/recollect", json={"what": ["toc"]}).status_code == 400
    assert "job_id" in client.post(f"/v1/books/{book['id']}/recollect", json={"what": ["metadata"]}).json()


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


def test_given_contents_pages_mark_printed_contents(stand, inbox):
    from stages import intake

    pdf = build(inbox / "c.pdf", [text_page(str(i)) for i in range(6)])
    book, _ = intake.register([(pdf, "c.pdf")], {"toc.contents_pages": [[2, 3]]})
    probed = intake.probe(book)
    assert probed["has_printed_contents"] is True
    assert probed["toc_sources"]["contents_pages_given"] == [[2, 3]]


def test_original_isbn_is_optional_and_not_missing(client, inbox, monkeypatch):
    monkeypatch.setattr(resolve, "gather", _fake_sources("A title"))
    book = client.post("/v1/books", json={"file_paths": [str(build(inbox / "o.pdf", [text_page("x")]))]}).json()
    resolve.collect(book["id"])
    fields = {f["name"]: f for f in client.get(f"/v1/books/{book['id']}/metadata").json()}
    assert fields["original_isbn"]["optional"] is True and fields["isbn"]["optional"] is False
    record = client.get(f"/v1/books/{book['id']}").json()["metadata"]
    assert "original_isbn" not in record["missing"] and "isbn" in record["not_found"]
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
