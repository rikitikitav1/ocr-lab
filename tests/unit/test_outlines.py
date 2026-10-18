import text_layer
from stages.structure import outlines
from stages.structure.sources import Entry


def _line(text, x, top, size=10.0):
    return text_layer.Line(text, x, top, size, False)


def _article(first: int, footnote: str) -> list[text_layer.Line]:
    return [_line("A Paper on Collective Bargaining", 180, 10, 17.0),
            _line(f"I. Introduction ........ {first}", 113, 30),
            _line(f"II. Foundations ........ {first + 2}", 113, 40),
            _line(f"1. Legal sources ........ {first + 2}", 138, 50),
            _line(f"2. Hierarchy ........ {first + 5}", 138, 60),
            _line(f"III. Summary ........ {first + 18}", 113, 70),
            _line("Body text of the paper begins here.", 113, 90, 12.0),
            _line(footnote, 113, 700, 8.0)]


def test_an_article_s_own_outline_becomes_its_children_with_levels_by_indent_and_a_footnote_number_ends_it():
    entries = [Entry("Contents", 1, 3), Entry("Part I", 1, 10), Entry("A Paper", 2, 20), Entry("Another Paper", 2, 46)]
    lines = {20: _article(3, "Recht der Gemeinschaften, Baden-Baden 1998, 273"), 21: [], 46: _article(29, "")}
    got, folded = outlines.fold(entries, lines, 17, 100)
    assert [(e.title, e.level, e.page) for e in got] == [
        ("Contents", 1, 3), ("Part I", 1, 10), ("A Paper", 2, 20),
        ("I. Introduction", 3, 20), ("II. Foundations", 3, 22), ("1. Legal sources", 4, 22), ("2. Hierarchy", 4, 25),
        ("III. Summary", 3, 38), ("Another Paper", 2, 46),
        ("I. Introduction", 3, 46), ("II. Foundations", 3, 48), ("1. Legal sources", 4, 48), ("2. Hierarchy", 4, 51),
        ("III. Summary", 3, 64)]
    assert [(f["page"], f["rows"], f["replaced"]) for f in folded] == [(20, 5, 0), (46, 5, 0)]
    # the book's own contents pages are no node's outline
    _, folded = outlines.fold(entries, lines, 17, 100, frozenset({20}))
    assert [f["page"] for f in folded] == [46]


def test_a_part_page_listing_the_part_s_own_children_and_a_book_without_an_offset_fold_nothing():
    entries = [Entry("Part I", 1, 10), Entry("One", 2, 12), Entry("Two", 2, 20), Entry("Three", 2, 30)]
    page = [_line("Part I", 150, 10, 17.0), _line("One ........ 1", 113, 30), _line("Two ........ 9", 113, 40),
            _line("Three ........ 19", 113, 50)]
    assert outlines.fold(entries, {10: page}, 11, 100) == (entries, [])
    assert outlines.fold(entries, {10: page}, None, 100) == (entries, [])
