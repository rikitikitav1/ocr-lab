from stages.toc import reconcile
from stages.toc.sources import Entry


def _e(title, level, page, verified=True, evidence=""):
    return Entry(title, level, page, verified=verified, evidence=evidence)


def test_the_printed_contents_is_the_base_and_a_bookmark_matched_by_a_normalised_title_votes_for_it():
    printed = [_e("1. Getting Started", 1, 10), _e("2. Basics", 1, 20)]
    marks = [_e("Chapter 1: Getting started", 1, 10), _e("Chapter 2: Basics", 1, 21)]
    base, merged, report = reconcile.reconcile({"printed_contents": printed, "bookmarks": marks})
    assert base == "printed_contents" and [e.title for e in merged] == ["1. Getting Started", "2. Basics"]
    assert all("bookmarks" in e.votes for e in merged) and report["matched"] == {"bookmarks": 2}
    assert report["conflicts"] == []


def test_a_base_whose_pages_the_text_does_not_confirm_gives_way_to_the_next_source():
    printed = [_e("One", 1, 10, verified=False), _e("Two", 1, 20, verified=False)]
    marks = [_e("One", 1, 10), _e("Two", 1, 20)]
    assert reconcile.reconcile({"printed_contents": printed, "bookmarks": marks})[0] == "bookmarks"


def test_levels_come_from_the_bookmarks_and_an_unmatched_entry_moves_onto_their_scale():
    printed = [_e("Intro", 1, 6), _e("Usage", 1, 12), _e("Details", 2, 14)]
    marks = [_e("Intro", 2, 6), _e("Usage", 2, 12)]
    _, merged, report = reconcile.reconcile({"printed_contents": printed, "bookmarks": marks})
    assert [(e.title, e.level, e.source) for e in merged] == [
        ("Intro", 2, "bookmarks"), ("Usage", 2, "bookmarks"), ("Details", 3, "printed_contents")]
    assert report["levels_from_bookmarks"]["moved"] == 3


def test_an_entry_two_other_sources_hold_comes_in_and_one_source_alone_does_not():
    printed = [_e("One", 1, 10), _e("Two", 1, 30)]
    marks = [_e("One", 1, 10), _e("Two", 1, 30), _e("Appendix", 1, 50, verified=False)]
    by_file = [_e("Appendix", 1, 50, verified=False), _e("Index", 2, 60, verified=False)]
    _, merged, report = reconcile.reconcile({"printed_contents": printed, "bookmarks": marks, "files": by_file})
    assert [e.title for e in merged] == ["One", "Two", "Appendix"]
    assert report["added"] == [{"title": "Appendix", "page": 50, "from": ["bookmarks", "files"]}]


def test_numbering_alone_never_makes_a_base_and_a_page_far_apart_is_a_conflict():
    counted = [_e("Chapter 1", 1, 3), _e("Chapter 2", 1, 9)]
    assert reconcile.reconcile({"numbering": counted})[0] is None
    printed = [_e("Setup", 1, 10), _e("Usage", 1, 20)]
    marks = [_e("Setup", 1, 10), _e("Usage", 1, 24)]
    _, _, report = reconcile.reconcile({"printed_contents": printed, "bookmarks": marks})
    assert report["conflicts"] == [{"title": "Usage", "printed_contents": 20, "bookmarks": 24}]
