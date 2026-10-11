from types import SimpleNamespace

from stages import running_heads


def _lines(*texts):
    return [SimpleNamespace(text=t) for t in texts]


def test_an_edge_line_on_three_pages_is_a_running_head_but_a_chapter_s_opening_title_is_not():
    lines = {1: _lines("Chapter 1 Basics", "body one", "Notes for Professionals 1"),
             2: _lines("Chapter 1 Basics", "body two", "Notes for Professionals 2"),
             3: _lines("Chapter 1 Basics", "body three", "Notes for Professionals 3"),
             4: _lines("body four", "Notes for Professionals 4")}
    assert running_heads.per_page(lines) == {1: [2], 2: [0, 2], 3: [0, 2], 4: [1]}
