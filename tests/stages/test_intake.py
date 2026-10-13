import pytest
import settings
from stages import intake

from tests.fixtures import build, contents_page, raster_page, text_page
from tests.real_db import needs_db

pytestmark = needs_db


@pytest.fixture
def files(tmp_path):
    a = build(tmp_path / "a.pdf", [text_page("Title page", bookmark="Front"), contents_page(), raster_page(),
                                   text_page("Chapter 1", bookmark="Chapter 1")])
    b = build(tmp_path / "b.pdf", [text_page("Chapter 2", bookmark="Chapter 2"), text_page("More")])
    return a, b


def test_same_files_in_same_order_are_one_book(stand, files):
    a, b = files
    first, created = intake.register([(a, "a.pdf"), (b, "b.pdf")])
    again, created_again = intake.register([(a, "a.pdf"), (b, "b.pdf")])
    assert created and not created_again and first == again


def test_a_book_folder_links_its_files_by_order_and_name(stand, files):
    a, b = files
    book, _ = intake.register([(a, "dir/a.pdf"), (b, "b.pdf")])
    folder = settings.DATA_DIR / "books" / str(book) / "source"
    assert sorted(p.name for p in folder.iterdir()) == ["0-a.pdf", "1-b.pdf"]
    assert (folder / "0-a.pdf").read_bytes() == a.read_bytes() and not (folder / "1-b.pdf").readlink().is_absolute()
    long, _ = intake.register([(b, "ж" * 200 + ".pdf")])
    (name,) = [p.name for p in (settings.DATA_DIR / "books" / str(long) / "source").iterdir()]
    assert len(name.encode()) <= 255 and name.endswith(".pdf")
    intake.link_sources(long)


def test_order_and_extra_files_make_another_book(stand, files):
    a, b = files
    one, _ = intake.register([(a, "a.pdf"), (b, "b.pdf")])
    reversed_, _ = intake.register([(b, "b.pdf"), (a, "a.pdf")])
    single, _ = intake.register([(a, "a.pdf")])
    assert len({one, reversed_, single}) == 3


def test_pages_run_across_files_and_layer_is_per_page(stand, files):
    a, b = files
    book, _ = intake.register([(a, "a.pdf"), (b, "b.pdf")])
    stored = intake.files_of(book)
    assert [(f.ord, f.first_page, f.pages) for f in stored] == [(0, 1, 4), (1, 5, 2)]
    assert (settings.DATA_DIR / stored[0].file_path).exists()
    probed = intake.probe(book)
    assert probed["text_layer"]["without_layer"] == [3]
    assert probed["has_bookmarks"] is True
    assert probed["has_printed_contents"] is True
    assert probed["toc_sources"]["bookmarks"] == 3


def test_probe_is_reused_when_files_did_not_change(stand, files, monkeypatch):
    a, b = files
    book, _ = intake.register([(a, "a.pdf")])
    intake.probe(book)
    monkeypatch.setattr(intake, "_probe", lambda files: pytest.fail("probed twice"))
    intake.probe(book)


def test_contents_at_the_end_of_the_book_count_as_printed_contents(stand, tmp_path):
    from tests.fixtures import FILLER

    body = [text_page(f"Chapter {n}", FILLER[:90]) for n in range(1, 71)]
    path = build(tmp_path / "late.pdf", [*body, contents_page()])
    book, _ = intake.register([(path, "late.pdf")])
    probed = intake.probe(book)
    assert probed["has_printed_contents"] is True and probed["toc_sources"]["printed_contents_pages"] == [71]


def test_a_listed_book_page_names_its_file_and_its_page_in_that_file():
    from types import SimpleNamespace

    files = [SimpleNamespace(ord=0, first_page=1, pages=10), SimpleNamespace(ord=1, first_page=11, pages=5)]
    assert intake.located(files, [3, 12, 12, 16]) == {3: [0, 3], 12: [1, 2]}
