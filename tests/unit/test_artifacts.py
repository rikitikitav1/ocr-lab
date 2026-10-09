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
    key = artifacts.input_hash(a=1)
    artifacts.write(owner, artifacts.book_dir(book), "intake", "probe.json", {"pages": 3}, key)
    assert artifacts.find_done(owner, "intake", "probe.json", key) is not None


def test_changed_inputs_are_not_reused(stand, book):
    owner = artifacts.Owner(book_id=book)
    artifacts.write(owner, artifacts.book_dir(book), "intake", "probe.json", {"pages": 3}, artifacts.input_hash(a=1))
    assert artifacts.find_done(owner, "intake", "probe.json", artifacts.input_hash(a=2)) is None


def test_a_file_changed_on_disk_is_not_reused(stand, book):
    import settings

    owner = artifacts.Owner(book_id=book)
    key = artifacts.input_hash(a=1)
    row = artifacts.write(owner, artifacts.book_dir(book), "intake", "probe.json", {"pages": 3}, key)
    (Path(settings.DATA_DIR) / row.path).write_text("tampered")
    assert artifacts.find_done(owner, "intake", "probe.json", key) is None


def test_crash_before_rename_leaves_no_file_and_no_row(stand, book, monkeypatch):
    import settings

    def crash(src, dst):
        raise OSError("killed")

    monkeypatch.setattr(os, "replace", crash)
    owner = artifacts.Owner(book_id=book)
    key = artifacts.input_hash(a=1)
    with pytest.raises(OSError):
        artifacts.write(owner, artifacts.book_dir(book), "intake", "probe.json", {"pages": 3}, key)
    target = Path(settings.DATA_DIR) / artifacts.book_dir(book) / "intake" / "probe.json"
    assert not target.exists()
    assert artifacts.find_done(owner, "intake", "probe.json", key) is None
