import json
import os
from pathlib import Path

import artifacts
import pytest

from tests.real_db import needs_db

pytestmark = needs_db


@pytest.fixture
def book(stand):
    from orm.catalogue import Book
    from orm.db import Session

    with Session() as session:
        row = Book(sha256=os.urandom(8).hex())
        session.add(row)
        session.commit()
        return row.id


def test_written_artifact_is_found_by_same_inputs(stand, book):
    owner = artifacts.Owner(book_id=book)
    made_from = artifacts.Inputs({"a": 1})
    artifacts.write(owner, artifacts.book_dir(book), "intake", "probe.json", {"pages": 3}, made_from)
    assert artifacts.find_done(owner, "intake", "probe.json", made_from.key) is not None


def test_each_input_part_is_hashed_into_the_manifest(stand, book):
    owner = artifacts.Owner(book_id=book)
    first = artifacts.write(owner, artifacts.book_dir(book), "intake", "probe.json", {"pages": 3},
                            artifacts.Inputs({"files": ["x"], "code": "c1"}), meta={"engine": "none"})
    second = artifacts.write(owner, artifacts.book_dir(book), "intake", "probe.json", {"pages": 3},
                             artifacts.Inputs({"files": ["x"], "code": "c2"}))
    assert first.meta["engine"] == "none"
    assert set(first.meta["inputs"]) == {"files", "code"}
    assert first.meta["inputs"]["files"] == second.meta["inputs"]["files"]
    assert first.meta["inputs"]["code"] != second.meta["inputs"]["code"]


def test_changed_inputs_are_not_reused(stand, book):
    owner = artifacts.Owner(book_id=book)
    artifacts.write(owner, artifacts.book_dir(book), "intake", "probe.json", {"pages": 3}, artifacts.Inputs({"a": 1}))
    assert artifacts.find_done(owner, "intake", "probe.json", artifacts.Inputs({"a": 2}).key) is None


def test_a_file_changed_on_disk_is_not_reused(stand, book):
    import settings

    owner = artifacts.Owner(book_id=book)
    made_from = artifacts.Inputs({"a": 1})
    row = artifacts.write(owner, artifacts.book_dir(book), "intake", "probe.json", {"pages": 3}, made_from)
    (Path(settings.DATA_DIR) / row.path).write_text("tampered")
    assert artifacts.find_done(owner, "intake", "probe.json", made_from.key) is None


def test_crash_before_rename_leaves_no_file_and_no_row(stand, book, monkeypatch):
    import settings

    def crash(src, dst):
        raise OSError("killed")

    monkeypatch.setattr(os, "replace", crash)
    owner = artifacts.Owner(book_id=book)
    made_from = artifacts.Inputs({"a": 1})
    with pytest.raises(OSError):
        artifacts.write(owner, artifacts.book_dir(book), "intake", "probe.json", {"pages": 3}, made_from)
    target = Path(settings.DATA_DIR) / artifacts.book_dir(book) / "intake" / "probe.json"
    assert not target.exists()
    assert artifacts.find_done(owner, "intake", "probe.json", made_from.key) is None


def test_a_keyed_file_written_from_other_inputs_leaves_the_earlier_one_whole(stand, book):
    owner = artifacts.Owner(book_id=book)
    first = artifacts.write(owner, artifacts.book_dir(book), "assemble", "reading.x.json", {"words": 1},
                            artifacts.Inputs({"build": "a"}), keyed=True)
    second = artifacts.write(owner, artifacts.book_dir(book), "assemble", "reading.x.json", {"words": 2},
                             artifacts.Inputs({"build": "b"}), keyed=True)
    assert first.path != second.path and json.loads(artifacts.read(first)) == {"words": 1}
    assert artifacts.find_done(owner, "assemble", "reading.x.json", artifacts.Inputs({"build": "a"}).key).id == first.id
