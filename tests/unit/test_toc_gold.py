from evaluation import toc_gold
from stages.toc.sources import Entry


def _e(title, level, page):
    return Entry(title, level, page)


GOLD = [_e("Chapter 1 Start", 1, 3), _e("Basics", 2, 4), _e("Chapter 2 Middle", 1, 10), _e("Chapter 3 End", 1, 20)]


def test_identical_tocs_find_every_chapter_on_its_page():
    scores = toc_gold.score(GOLD, list(GOLD))
    assert (scores["chapters_found"], scores["extra_chapters"], scores["recall"], scores["precision"],
            scores["level_agreement"]) == (3, 0, 1.0, 1.0, 1.0)


def test_a_chapter_on_another_page_is_missed_and_named_with_where_it_went():
    got = [_e("Chapter 1 Start", 1, 3), _e("Basics", 2, 4), _e("2 Middle", 1, 14), _e("Chapter 3 End", 1, 20)]
    scores = toc_gold.score(GOLD, got)
    assert scores["chapters_found"] == 2 and scores["extra_chapters"] == 1
    assert scores["missed_chapters"] == [{"title": "Chapter 2 Middle", "page": 10,
                                          "found_as": {"title": "2 Middle", "page": 14, "level": 1}}]


def test_a_shifted_level_lowers_level_agreement_and_an_extra_entry_lowers_precision():
    got = [_e("Chapter 1 Start", 1, 3), _e("Basics", 1, 4), _e("Chapter 2 Middle", 1, 10),
           _e("Chapter 3 End", 1, 20), _e("Index", 2, 30)]
    scores = toc_gold.score(GOLD, got)
    assert scores["level_agreement"] == 0.75 and scores["precision"] == 0.8 and scores["recall"] == 1.0


def test_a_chapter_found_below_the_top_still_counts_and_front_pages_are_not_chapters():
    gold = [_e("Cover", 1, 1), _e("Contents", 1, 2)] + GOLD[:]
    got = [_e("Part One", 1, 3), _e("Chapter 1 Start", 2, 3), _e("Chapter 2 Middle", 2, 10), _e("Chapter 3 End", 2, 20)]
    scores = toc_gold.score(gold, got, contents_end=2)
    assert scores["chapters"] == 3 and scores["chapters_found"] == 3 and scores["chapters_below_top"] == 3
    assert [c["title"] for c in scores["not_counted"]] == ["Cover", "Contents"]


def test_a_hips_gold_reads_commas_quotes_and_drops_a_single_root(tmp_path, monkeypatch):
    from evaluation import hips

    monkeypatch.setattr(hips, "folder", lambda: tmp_path)
    (tmp_path / "GT_TOCs").mkdir()
    (tmp_path / "GT_TOCs" / "b.toc").write_text('﻿1,Swiss Law,2\n2,Law, Governance, and Development,3\n'
                                                 '3,"Goals, priorities",5\n\n', encoding="utf-8")
    got = [(e.title, e.level, e.page) for e in hips.gold("b")]
    assert got == [("Law, Governance, and Development", 2, 3), ("Goals, priorities", 3, 5)]
    (tmp_path / "GT_TOCs" / "c.toc").write_text("1,One,3\n1,Two,9\n", encoding="utf-8")
    assert [e.title for e in hips.gold("c")] == ["One", "Two"]


def test_a_hips_gold_skips_a_line_without_a_page_and_a_trailing_comma(tmp_path, monkeypatch):
    from evaluation import hips

    monkeypatch.setattr(hips, "folder", lambda: tmp_path)
    (tmp_path / "GT_TOCs").mkdir()
    (tmp_path / "GT_TOCs" / "d.toc").write_text("1,One,3\n3,Rev. Rul. 91-31\n1,Two,177,\n", encoding="utf-8")
    assert [(e.title, e.page) for e in hips.gold("d")] == [("One", 3), ("Two", 177)]


def test_a_title_with_an_author_before_it_or_odd_spacing_is_the_same_chapter():
    gold = [_e("Marc Thommen Swiss Legal System", 1, 26), _e("Part I. Introduction", 1, 11)]
    got = [_e("Swiss Legal System", 1, 27), _e("Part I . Introduction", 1, 11)]
    assert toc_gold.score(gold, got)["chapters_found"] == 2
    assert toc_gold.score([_e("Introduction", 1, 5)], [_e("Conclusion", 1, 5)])["chapters_found"] == 0


def test_a_top_entry_the_gold_lists_deeper_is_not_extra():
    got = [_e("Chapter 1 Start", 1, 3), _e("Basics", 1, 4), _e("Chapter 2 Middle", 1, 10), _e("Chapter 3 End", 1, 20)]
    assert toc_gold.score(GOLD, got)["extra_chapters"] == 0


def test_a_bookmark_with_only_the_label_is_the_chapter_opening_with_it():
    assert toc_gold.score([_e("Unit I:", 1, 5)], [_e("Unit I: The Core Structures", 1, 5)])["chapters_found"] == 1
    assert toc_gold.score([_e("Unit I:", 1, 5)], [_e("Unit II: Other", 1, 5)])["chapters_found"] == 0


def test_service_rows_of_an_empty_toc_are_none():
    from evaluation import toc_run

    assert toc_run._service([], "bookmarks", 100, frozenset(), []) == []


def test_service_rows_come_from_the_run_s_own_chapters_so_the_printed_contents_page_is_not_one():
    from types import SimpleNamespace

    from evaluation import toc_run

    got = [_e("Contents", 1, 2), _e("Preface", 1, 3), _e("1 Start", 1, 5), _e("2 Middle", 1, 20),
           _e("Index", 1, 95)]
    service = toc_run._service(got, "bookmarks", 100, frozenset({2}), [SimpleNamespace(file_name="book.pdf")])
    assert [e.title for e in service] == ["Preface", "Index"]
