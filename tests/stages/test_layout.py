import json

from pdf import Line
from stages.layout import headings, page

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
