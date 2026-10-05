# one test per blocking finding of the first review round
import job_handlers
import job_queue
import net
import pytest
import worker
from orm.db import Session
from orm.jobs import Job
from stages.metadata import resolve, title_pages

from tests.real_db import needs_db


def _due(id: int) -> None:
    with Session() as session:
        job = session.get(Job, id)
        job.apply_since = job.created_at
        session.commit()


@needs_db
def test_a_deferred_job_runs_on_its_next_claim(stand, monkeypatch):
    calls = []

    def handler(options):
        calls.append(1)
        if len(calls) == 1:
            raise job_handlers.Deferred("model away", delay_seconds=1)
        return {"ok": True}

    monkeypatch.setitem(job_handlers.HANDLERS, "noop", handler)
    id = job_queue.enqueue("noop")
    assert worker.run_once("cpu")
    _due(id)
    assert worker.run_once("cpu")
    job = job_queue.get(id)
    assert job.status == "done" and job.deferred_seconds == 1 and "_deferred_seconds" not in job.options


def test_a_dead_supervisor_reads_as_down_and_a_silent_one_as_unknown(monkeypatch):
    from engines import converter

    def down(url, **kw):
        raise net.SourceDown("converter-docling", "ConnectError: refused")

    def silent(url, **kw):
        raise net.SourceDown("converter-docling", "ReadTimeout: timed out")

    monkeypatch.setattr(net, "get", down)
    assert converter.reading("docling")[0] == converter.DOWN
    monkeypatch.setattr(net, "get", silent)
    assert converter.reading("docling")[0] == converter.UNKNOWN


def test_an_away_model_defers_the_subject_instead_of_leaving_it_empty(monkeypatch):
    from stages.metadata import model_reader

    def away(*a, **kw):
        raise job_handlers.Deferred("ollama away")

    monkeypatch.setattr(model_reader, "subject", away)
    with pytest.raises(job_handlers.Deferred):
        resolve._subject("A title", "pages", "body")


def test_bookvoed_translators_can_win():
    assert "catalogue:bookvoed" in resolve.RANK["translators"]


@pytest.mark.parametrize("a,b,same", [("5-85-104-0", "", False), ("080442957X", "9780804429573", True),
                                      ("978-5-4461-4313-9", "9785446143139", True),
                                      ("1593279507", "9781718504103", False)])
def test_one_isbn_comparison(a, b, same):
    assert title_pages.same_isbn(a, b) is same


def test_isbn_keeps_its_x():
    assert title_pages.normalise_isbn("0-8044-2957-x") == "080442957X"


@needs_db
def test_a_cancel_reaches_queued_children(stand):
    parent = job_queue.enqueue("noop")
    child = job_queue.enqueue("noop", parent_id=parent)
    assert set(job_queue.cancel([parent])) == {parent, child}
