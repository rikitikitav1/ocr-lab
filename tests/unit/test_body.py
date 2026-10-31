from elements import body
from text_layer import Line


def _page(p: int, notes: int) -> list:
    head = [Line(f"Running head of the book {p}", 50, 20, 9, False)]
    text = [Line(f"body text of page {p} line {i} goes on", 50, 100 + 12 * i, 10, False) for i in range(8)]
    foot = [Line(f"note {i} of page {p} cites a long source with many words in it", 50, 500 + 9 * i, 8, False)
            for i in range(notes)]
    return head + text + foot


def test_the_body_is_what_pages_open_with_under_the_band_though_notes_outweigh_it():
    lines = {p: _page(p, 12) for p in range(1, 21)}
    band = frozenset(id(ls[0]) for ls in lines.values())
    assert body.by_characters(lines) == (8, False)
    assert body.learn(lines, band) == (10, False)
    assert body.learn(lines) == (8, False)


def test_an_opening_style_that_sets_little_of_the_book_is_no_body():
    big = [Line(f"a big opening line {i} here", 50, 30 + 20 * i, 16, False) for i in range(3)]
    lines = {p: [*big, *_page(p, 0)[1:]] for p in range(1, 21)}
    for ls in lines.values():
        ls.extend(Line(f"more body text that runs on and on {i}", 50, 300 + 12 * i, 10, False) for i in range(30))
    assert body.learn(lines, frozenset({0})) == (10, False)
