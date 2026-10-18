import artifacts
import settings
from orm.catalogue import Artifact, Book
from orm.db import Session
from sqlalchemy import select
from stages.structure import collect

from tests.doors.test_runs import TEXT, _drain, engines
from tests.fixtures import build, text_page
from tests.real_db import needs_db

pytestmark = needs_db


def _two_runs(client, inbox, monkeypatch) -> tuple[int, int, int]:
    pages = [text_page("One", TEXT, bookmark="One"), text_page("Two", TEXT, bookmark="Two")]
    book = client.post("/v1/books", json={"file_paths": [str(build(inbox / "clean.pdf", pages))],
                                          "then": []}).json()["id"]
    collect.collect(book)
    engines(monkeypatch)
    first = client.post(f"/v1/books/{book}/runs", json={}).json()["run"]["id"]
    _drain()
    second = client.post(f"/v1/books/{book}/runs", json={}).json()["run"]["id"]
    _drain()
    return book, first, second


def _heavy(run_id: int, book_id: int, name: str) -> Artifact:
    return artifacts.write(artifacts.Owner(run_id=run_id), artifacts.run_dir(book_id, run_id), "assemble", name,
                           [{"block": 1}], artifacts.Inputs({"n": name}), piece_ord=1, heavy=True)


def test_cleanup_lists_then_removes_only_heavy_files_of_runs_that_are_not_the_result(client, inbox, monkeypatch):
    book, first, second = _two_runs(client, inbox, monkeypatch)
    with Session() as session:
        result = session.get(Book, book).result_run_id
    other = first if result == second else second
    kept, gone = _heavy(result, book, "model.0.1.kept.json"), _heavy(other, book, "model.0.1.gone.json")
    listed = client.post("/v1/cleanup", json={}).json()
    assert listed["dry_run"] and other in listed["runs"] and result not in listed["runs"]
    assert (settings.DATA_DIR / gone.path).exists()
    done = client.post("/v1/cleanup", json={"dry_run": False}).json()
    assert done["files"] == listed["files"] and not (settings.DATA_DIR / gone.path).exists()
    assert (settings.DATA_DIR / kept.path).exists()
    with Session() as session:
        assert session.get(Artifact, gone.id).removed_at is not None
        reports = session.scalars(select(Artifact).where(Artifact.run_id == other, Artifact.name == "report.json"))
        assert all(a.removed_at is None for a in reports)
    assert client.get(f"/v1/runs/{other}/bundle").status_code == 200
    assert client.post("/v1/cleanup", json={}).json()["files"] == 0


def test_deleting_the_result_run_moves_the_result_to_the_next_run_and_removes_its_files(client, inbox, monkeypatch):
    book, first, second = _two_runs(client, inbox, monkeypatch)
    with Session() as session:
        result = session.get(Book, book).result_run_id
    other = first if result == second else second
    run_dir = settings.DATA_DIR / artifacts.run_dir(book, result)
    assert run_dir.exists()
    deleted = client.delete(f"/v1/runs/{result}")
    assert deleted.status_code == 200, deleted.text
    assert deleted.json() == {**deleted.json(), "deleted": result, "was_result": True, "result_run_id": other}
    assert client.get(f"/v1/runs/{result}").status_code == 404 and not run_dir.exists()
    with Session() as session:
        assert session.get(Book, book).result_run_id == other
        assert session.scalar(select(Artifact).where(Artifact.run_id == result)) is None
    assert client.delete(f"/v1/runs/{result}").status_code == 404
