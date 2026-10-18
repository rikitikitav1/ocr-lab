import json

from stages.layout import headings, page
from text_layer import Line

LETTERS = "abcdefghijklmnopqrstuvwxyzabcd"


def _book(pages: int = 20, foot=None) -> dict:
    out = {}
    for p in range(1, pages + 1):
        lines = [Line(f"Chapter {p % 3}   {p + 2}", 50, 40.6, 9, False)]
        lines += [Line(f"a body line {LETTERS[i]} of the page {LETTERS[p]}", 50, 100 + 12 * i, 10, False)
                  for i in range(30)]
        lines += foot(p) if foot else []
        out[p] = lines
    return out


def test_the_top_slot_carries_the_folio_and_the_body_is_not_a_slot():
    found, _ = page.measure(_book())
    assert found["body"] == 10
    assert found["top"]["folio"] == {"offset": -2, "pages": 20}
    assert found["bottom"] is None


def test_notes_open_with_a_marker_and_code_under_the_body_is_no_note():
    notes, _ = page.measure(_book(foot=lambda p: [Line(f"1 See {LETTERS[p]} on the source.", 50, 500, 8, False)]))
    assert notes["notes"] == {"size": 8.0, "pages": 20, "lines": 20}
    code, _ = page.measure(_book(foot=lambda p: [Line(f"Program Example{LETTERS[p]};", 50, 500, 8, False)]))
    assert code["notes"] is None and code["bottom"] is None


def test_a_label_above_a_heading_is_told_by_its_shape_not_its_size():
    lines = {5: [Line("CHAPTER 2", 50, 100, 30, True), Line("Data Architectures", 50, 140, 20, True),
                 Line("body text here", 50, 200, 10, False)]}
    found = headings.measure(lines, set(), [{"title": "Chapter 2. Data Architectures", "level": 1, "first_page": 5}])
    assert found["levels"][0]["size"] == 20
    assert found["levels"][0]["pinned"] == 1


def test_a_heading_on_its_own_line_is_not_pinned_to_the_bigger_line_above():
    lines = {90: [Line("Reference for unit 'ascii85'", 50, 100, 25, True), Line("1.1 Used units", 50, 140, 14, True),
                  Line("body text here", 50, 200, 10, False)]}
    found = headings.measure(lines, set(), [{"title": "1.1 Used units", "level": 2, "first_page": 90}])
    assert found["levels"][0]["size"] == 14
    assert found["levels"][0]["holds"] is None


def test_a_kept_page_layout_claims_the_same_lines_it_was_measured_on():
    lines = _book(foot=lambda p: [Line(f"1 See {LETTERS[p]} on the source.", 50, 500, 8, False)])
    found, taken = page.measure(lines)
    kept = json.loads(json.dumps(found))
    assert taken and page.claimed(lines, kept) == taken


def test_a_layout_made_from_other_inputs_is_stale_and_one_never_made_is_not(monkeypatch):
    from types import SimpleNamespace

    from stages.layout import collect

    kept = {collect.PAGE: SimpleNamespace(input_hash="old"), collect.HEADINGS: None}
    monkeypatch.setattr(collect, "current", lambda book_id, kind: kept[kind])
    monkeypatch.setattr(collect, "inputs", lambda book_id, kind, sv=None: SimpleNamespace(key="new"))
    assert collect.stale(1, collect.PAGE) and not collect.stale(1, collect.HEADINGS)
    monkeypatch.setattr(collect, "inputs", lambda book_id, kind, sv=None: SimpleNamespace(key="old"))
    assert not collect.stale(1, collect.PAGE)


def test_a_head_set_on_its_side_is_a_side_band_and_does_not_take_the_top_slot():
    def turned(p):
        x = 20 if p % 2 else 330
        return [Line("Part I. Anatomy of the ear", x, 300, 7.5, False, True)]

    book = _book()
    plain, _ = page.measure(book)
    sided = {p: turned(p) + lines for p, lines in book.items()}
    found, taken = page.measure(sided)
    assert found["top"] == plain["top"] and found["bottom"] == plain["bottom"]
    assert [(s["band"], s["size"]) for s in found["sides"]] == [([20, 20], 7.5), ([330, 330], 7.5)]
    assert all(id(lines[0]) in taken for lines in sided.values())
    assert sum(id(x) in page.claimed(sided, found) for lines in sided.values() for x in lines[:1]) == len(sided)
    # a turned table spreads across a landscape page: no side band
    wide = {p: [Line(f"col {p}", 100 + 30 * i, 300, 9, False, True) for i in range(8)] + lines
            for p, lines in book.items()}
    assert page.measure(wide)[0]["sides"] == []
    # one turned table page among the heads leaves the heads' band as it is
    mixed = {**sided, 3: [Line(f"cell {i}", 45 + 14 * i, 300, 7.5, False, True) for i in range(25)] + book[3]}
    assert [s["band"] for s in page.measure(mixed)[0]["sides"]] == [[20, 20], [330, 330]]


def test_a_claimed_slot_line_has_a_reason_and_a_band_line_by_place_alone_has_none():
    book = _book()
    found, _ = page.measure(book)
    reasons = page.claimed_reasons(book, found)
    assert {why for _, why in reasons.values()} == {"folio"}
    assert len(reasons) == len(book)
    stray = {p: [Line(f"a body line {LETTERS[p]} that ends the page", 50, 40.6, 9, False)] + lines[1:]
             for p, lines in book.items()}
    assert page.claimed_reasons(stray, found) == {}


def test_the_front_matter_s_roman_folios_are_their_own_sequence_before_the_first_arabic_one():
    romans = ["i", "ii", "iii", "iv", "v", "vi"]

    def foot(p):
        number = romans[p - 1] if p <= len(romans) else str(p - len(romans))
        return [Line(number, 200, 560, 9, False)]

    book = _book(pages=28, foot=foot)
    for p in book:
        book[p] = [x for x in book[p] if not x.text.startswith("Chapter")]
    found, _ = page.measure(book)
    assert found["bottom"]["folio"]["offset"] == 6
    assert found["bottom"]["roman"] == {"offset": 0, "pages": 6, "before": 7}
    reasons = page.claimed_reasons(book, found)
    assert sorted(x.text for x, why in reasons.values() if why == "folio")[:3] == ["1", "10", "11"]
    assert {x.text for x, _ in reasons.values()} >= set(romans)
