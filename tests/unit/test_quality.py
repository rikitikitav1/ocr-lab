from document.model import Code, Figure, Heading, PageMarker, Paragraph
from document.model import Piece as Model
from quality import book, piece

LAYER = "The quick brown fox jumps over the lazy dog while the cat sleeps by the warm fire tonight and every night"


def _chapter(blocks, first=1, last=1, title=""):
    return Model(ord=1, title=title, level=1, first_page=first, last_page=last, blocks=blocks)


def _page(n):
    return PageMarker(book_page=n, file_ord=0, file_page=n)


def test_a_chapter_true_to_its_layer_loses_nothing_and_finds_its_sections():
    got = _chapter([_page(1), Heading(text="Basics", level=2, level_source="docling"), Paragraph(text=LAYER)])
    checks = piece.check(got, [("Basics", 2)], {1: f"Basics {LAYER}"})
    assert (checks["lost_text"], checks["extra_text"], checks["subs_found"]) == (0.0, 0.0, 1)


def test_a_page_with_a_thin_layer_is_left_out_so_a_cover_s_ocr_does_not_count():
    got = _chapter([_page(1), Paragraph(text="garbage from a screenshot"), _page(2), Paragraph(text=LAYER)], 1, 2)
    checks = piece.check(got, [], {1: "Cover", 2: LAYER})
    assert (checks["layer_pages"], checks["lost_text"], checks["extra_text"]) == (1, 0.0, 0.0)


def test_lost_and_extra_text_are_shares_of_words():
    lost = _chapter([_page(1), Paragraph(text="The quick brown fox and some noise")])
    checks = piece.check(lost, [], {1: LAYER})
    assert (checks["lost_words"], checks["lost_text"]) == (16, 0.762)
    assert (checks["extra_words"], checks["extra_text"]) == (2, 0.286)


def test_the_layer_s_running_heads_are_not_lost_text():
    head = "GoalKicker com PostgreSQL Notes for Professionals 15"
    got = _chapter([_page(1), Paragraph(text=LAYER)])
    assert piece.check(got, [], {1: f"{LAYER} {head}"})["lost_text"] > 0
    checks = piece.check(got, [], {1: f"{LAYER} {head}"}, {"layer": [head], "docling": [head], "mineru": []})
    assert (checks["lost_text"], checks["set_aside_words"]) == (0, 0)


def test_a_block_an_engine_set_aside_beyond_the_layer_s_heads_is_lost_and_counted():
    caption = "Figure one shows the planner"
    got = _chapter([_page(1), Paragraph(text=LAYER)])
    checks = piece.check(got, [], {1: f"{LAYER} {caption}"}, {"layer": [], "docling": [caption]})
    assert (checks["lost_words"], checks["set_aside_words"]) == (5, 5)


def test_a_figure_without_an_image_file_is_counted():
    got = _chapter([_page(1), Paragraph(text=LAYER), Figure(image="picture 3"), Figure(image="images/01-001.png")])
    checks = piece.check(got, [], {1: LAYER})
    assert (checks["figures"], checks["figures_not_kept"]) == (2, 1)


def test_the_book_sums_its_chapters_words_and_names_the_worst_ones():
    long = "A paragraph long enough to count as a page taken twice by two chapters' ranges " * 2
    doubled = book.duplicates({1: long, 2: f"{long}\n\nother", 3: f"```\n{long}\n```"})
    assert [d["pieces"] for d in doubled] == [[1, 2]]

    def done(ord, lost, words, subs, found):
        return {"ord": ord, "title": str(ord), "status": "done",
                "checks": {"lost_words": lost, "layer_words": words, "extra_words": 0, "lost_text": lost / words,
                           "layer_pages": 1, "subs": subs, "subs_found": found}}

    pieces = [done(1, 10, 100, 2, 2), done(2, 30, 100, 3, 1), {"ord": 3, "title": "3", "status": "failed",
                                                                 "checks": {}}]
    got = book.numbers(pieces, doubled)
    assert (got["lost_text"], got["pieces_failed"], got["subs_found"], got["duplicates"]) == (0.2, [3], 3, 1)
    assert [c["ord"] for c in got["worst"]["lost_text"]] == [2, 1]
    assert got["worst"]["subs_missing"] == [{"ord": 2, "title": "2", "missing": 2}]


def test_the_chapter_title_the_writer_puts_on_top_is_not_lost_text():
    got = _chapter([_page(1), Paragraph(text=LAYER)], title="One")
    assert piece.check(got, [], {1: f"One {LAYER}"})["lost_text"] == 0


def test_recognised_pages_report_the_engines_agreement_and_stay_out_of_the_layer_shares():
    got = _chapter([_page(1), Paragraph(text=LAYER), _page(2), Paragraph(text="recognised words")], 1, 2)
    checks = piece.check(got, [], {1: LAYER}, None, {2: 0.8, 3: 0.4})
    assert (checks["lost_text"], checks["extra_text"]) == (0.0, 0.0)
    assert (checks["recognised_pages"], checks["agreement"], checks["agreement_min"]) == (2, 0.6, 0.4)


def test_words_from_pages_without_a_layer_are_counted_apart():
    got = _chapter([_page(1), Paragraph(text=LAYER), _page(2), Paragraph(text="thumbnail of another book cover"),
                    _page(3), Paragraph(text="recognised words")], 1, 3)
    checks = piece.check(got, [], {1: LAYER, 2: ""}, None, {3: 0.9})
    assert (checks["layerless_words"], checks["extra_text"]) == (7, 0.0)


def test_a_paragraph_written_twice_in_a_chapter_is_counted_once_as_repeated():
    long = "A paragraph long enough to be counted when an engine writes it a second time in the same chapter " * 2
    got = _chapter([_page(1), Paragraph(text=long), Paragraph(text=long), Paragraph(text="short"),
                    Paragraph(text="short")])
    assert piece.check(got, [], {1: LAYER})["repeated_paragraphs"] == 1


def test_layer_word_runs_written_out_of_their_order_are_counted():
    first, second = LAYER[:LAYER.index(" while")], LAYER[LAYER.index("while"):]
    kept = piece.check(_chapter([_page(1), Paragraph(text=first), Paragraph(text=second)]), [], {1: LAYER})
    swapped = piece.check(_chapter([_page(1), Paragraph(text=second), Paragraph(text=first)]), [], {1: LAYER})
    assert (kept["out_of_order"], kept["order_anchors"]) == (0.0, 16)
    assert (swapped["order_anchors"], swapped["out_of_order_anchors"]) == (11, 4)


def test_the_book_shares_its_out_of_order_runs_over_its_anchors():
    def done(ord, anchors, moved):
        return {"ord": ord, "title": str(ord), "status": "done",
                "checks": {"order_anchors": anchors, "out_of_order_anchors": moved, "out_of_order": moved / anchors,
                           "repeated_paragraphs": 1}}

    got = book.numbers([done(1, 90, 0), done(2, 10, 5)], [])
    assert (got["out_of_order"], got["repeated_paragraphs"]) == (0.05, 2)
    assert [c["ord"] for c in got["worst"]["out_of_order"]] == [2]
    assert [c["ord"] for c in got["worst"]["repeated_paragraphs"]] == [1, 2]


def test_a_letter_spaced_heading_finds_its_toc_title():
    got = _chapter([_page(1), Heading(text="1 .1 . К Л И Н И Ч ЕС К АЯ АНАТОМ И Я Н А Р У Ж Н О Г О НОСА", level=2,
                                      level_source="mineru"), Paragraph(text=LAYER)])
    checks = piece.check(got, [("1.1. Клиническая анатомия наружного носа", 2), ("1.2. Другой раздел", 2)],
                           {1: LAYER})
    assert (checks["subs_found"], checks["subs_missing"]) == (1, ["1.2. Другой раздел"])


def test_a_chapter_reports_its_deepest_heading_and_none_at_its_own_level():
    got = piece.check(_chapter([_page(1), Heading(text="Part", level=1, level_source="structure"),
                                  Heading(text="Deep", level=3, level_source="mineru"), Paragraph(text=LAYER)]),
                        [], {1: LAYER})
    assert (got["max_heading_level"], got["headings_not_below_title"]) == (5, 0)
    assert got["heading_sources"] == {"structure": 1, "mineru": 1}


def test_the_book_names_chapters_below_their_own_sections_and_sums_extra_over_what_reached_it():
    def done(ord, extra, level, above):
        return {"ord": ord, "title": str(ord), "status": "done",
                "checks": {"layer_words": 100, "lost_words": 10, "extra_words": extra, "max_heading_level": level,
                           "headings_not_below_title": above}}

    got = book.numbers([done(1, 0, 3, 0), done(2, 20, 6, 1)], [])
    assert (got["max_heading_level"], got["pieces_below_sections"]) == (6, [2])
    assert got["extra_text"] == round(20 / (200 - 20 + 20), 3)
    assert [c["ord"] for c in got["worst"]["max_heading_level"]] == [2]


def test_the_book_s_own_running_head_left_as_a_paragraph_is_counted():
    got = piece.check(_chapter([_page(1), Paragraph(text="CHAPTER 3. STREAMS 41"), Paragraph(text=LAYER)]),
                        [], {1: LAYER}, {"layer": ["Chapter 3. Streams 40"]})
    assert got["running_heads_in_text"] == 1
    kept = piece.check(_chapter([_page(1), Heading(text="Chapter 3. Streams", level=1, level_source="structure"),
                                   Paragraph(text="41"), Paragraph(text=LAYER)]),
                         [], {1: LAYER}, {"layer": ["Chapter 3. Streams 40", "41"]})
    assert kept["running_heads_in_text"] == 1


def test_heading_levels_are_read_from_the_written_markdown_past_code_comments():
    got = piece.check(_chapter([_page(1), Code(text="# not a heading\nls"), Heading(text="Deep", level=2,
                                                                                       level_source="mineru")]),
                        [], {})
    assert (got["max_heading_level"], got["headings_not_below_title"]) == (4, 0)


def test_recognised_pages_report_the_share_of_words_a_dictionary_knows_and_none_for_a_spaceless_language():
    got = _chapter([_page(1), Paragraph(text="Книга о мире и ри гедие")])
    share = piece.check(got, [], {}, recognised={1: 0.5}, languages=["ru"])
    assert share["dictionary_words"] == 4 and share["dictionary_share"] == 0.75
    assert piece.check(got, [], {}, recognised={1: 0.5}, languages=["en", "zh"])["dictionary_share"] is None


def test_a_book_language_wordfreq_lacks_leaves_the_dictionary_share_unknown_rather_than_low():
    got = _chapter([_page(1), Paragraph(text="Книга о мире и ри гедие")])
    assert piece.check(got, [], {}, recognised={1: 0.5}, languages=["ru", "la"])["dictionary_share"] is None

