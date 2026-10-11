from document.model import Heading, PageMarker, Paragraph
from evaluation import element_gold
from pdf import Line

GOLD = """## Branching

Text before.

```bash
git branch testing
git checkout testing
```

| Command | Effect |
|---|---|
| `branch` | makes a branch |

### Switching
"""


def test_code_contained_survives_a_split_and_exact_needs_the_same_lines():
    got = "```\ngit branch testing\n```\n\n```\ngit checkout testing\n```\n"
    scores = element_gold.score(GOLD, got, [], set())
    assert (scores["code"], scores["code_contained"], scores["code_exact"], scores["code_out"]) == (1, 0, 0, 2)
    whole = "```\ngit branch testing\ngit checkout testing\n```\n"
    scores = element_gold.score(GOLD, whole, [], set())
    assert (scores["code_contained"], scores["code_exact"], scores["code_out_foreign"]) == (1, 1, 0)


def test_cells_are_a_multiset_and_rule_rows_do_not_count():
    got = "<table><tr><th>Command</th><th>Effect</th></tr><tr><td>branch</td><td>makes a branch</td></tr></table>"
    scores = element_gold.score(GOLD, got, [], set())
    assert (scores["cells"], scores["cells_found"]) == (4, 4)


def test_headings_inside_code_are_not_headings():
    assert element_gold.headings("```\n# a comment\n```\n## Real") == ["Real"]


def test_the_section_is_what_lies_inside_the_gold_boxes_whatever_the_headings():
    from document.model import Where

    def at(page, top):
        return Where(page=page, box=(0.1, top, 0.9, top + 0.05), engine="x")

    blocks = [PageMarker(book_page=1, file_ord=0, file_page=1), Paragraph(text="before", where=at(1, 0.1)),
              Heading(text="Branching", level=2, level_source="x", where=at(1, 0.5)),
              Heading(text="A term set as a heading", level=2, level_source="x", where=at(1, 0.7)),
              PageMarker(book_page=2, file_ord=0, file_page=2), Paragraph(text="still ours", where=at(2, 0.1)),
              Heading(text="Next section", level=2, level_source="x", where=at(2, 0.6)),
              Paragraph(text="no place on a section page")]
    cut, unplaced = element_gold.section(blocks, [(1, (0, 0.45, 1, 1)), (2, (0, 0, 1, 0.5))])
    assert [getattr(b, "text", "page") for b in cut] == [
        "page", "Branching", "A term set as a heading", "page", "still ours", "no place on a section page"]
    assert unplaced == 1


def test_a_running_head_is_a_line_on_the_edge_of_two_pages_and_its_leak_is_counted():
    def page(*texts):
        return [Line(t, 30, 40 + 14 * i, 10, False) for i, t in enumerate(texts)]

    lines = {0: page("Chapter 3 Git Branching", "body", "58"), 1: page("Chapter 3 Git Branching", "more", "59")}
    running = element_gold.running_lines(lines)
    assert "chapter git branching" in running
    blocks = [PageMarker(book_page=1, file_ord=0, file_page=1), Paragraph(text="Chapter 3 Git Branching")]
    assert element_gold.score("", "", blocks, running)["running_leaked"] == 1


def test_best_of_both_takes_each_element_from_the_engine_that_read_it_best():
    from evaluation import element_run

    base = {"id": "s", "doc": "d", "lang": "en", "unplaced": 0, "unknown": {}, "code_out_foreign": 0,
            "code_out_merged": 0,
            "headings_phantom": 0, "running_leaked": 0, "similarity": 90, "body_f1": 0.9, "code_exact": 0,
            "code_contained": 0, "cells_found": 0, "table_rows_exact": 0, "headings_found": 0}
    rows = [dict(base, engine="docling", code_contained=3, cells_found=1),
            dict(base, engine="mineru", code_contained=1, cells_found=5, running_leaked=2)]
    best = element_run._best_of(rows)[0]
    assert (best["code_contained"], best["cells_found"], best["running_leaked"]) == (3, 5, 0)


def test_an_indented_block_after_a_blank_line_is_code_but_a_list_continuation_is_not():
    gold = "Text:\n\n    proxy :: f a -> a\n    proxy = undefined\n\nMore.\n\n-   item\n\n    continued item text\n"
    assert element_gold.code_blocks(gold) == ["proxy :: f a -> a\nproxy = undefined\n"]


def test_a_gold_is_checked_against_the_lines_inside_its_own_boxes():
    def page(*texts):
        return [Line(t, 30, 100 + 100 * i, 10, False) for i, t in enumerate(texts)]

    lines = {0: page("other section words here", "the real section text", "more of the real section")}
    clips = [(1, (0, 0.18, 1, 0.42))]
    got = element_gold.gold_in_clips("the real section text more of the real section", lines, clips, [(500, 1000)])
    assert got["gold_clip_f1"] > 0.9 and got["clip_words"] == 9
    assert element_gold.gold_in_clips("other section words here", lines, clips, [(500, 1000)])["gold_clip_f1"] < 0.3


def test_word_f1_ignores_punctuation_set_apart():
    assert element_gold._f1("слово, слово", "слово , слово") == 1.0


def test_a_table_row_with_a_shifted_cell_is_not_the_same_row():
    gold = "| Feature | A | B |\n|---|---|---|\n| sync | yes |  |\n"
    shifted = "<table><tr><td>Feature</td><td>A</td><td>B</td></tr><tr><td>sync</td><td></td><td>yes</td></tr></table>"
    right = ("<table><tr><th>Feature</th><th colspan=\"1\">A</th><th>B</th></tr>"
             "<tr><td>sync</td><td>yes</td><td></td></tr></table>")
    assert element_gold.score(gold, shifted, [], set())["table_rows_exact"] == 1
    assert element_gold.score(gold, right, [], set())["table_rows_exact"] == 2


def test_rows_ignore_spaces_and_marks_in_cells_but_a_broken_hyphen_is_counted():
    gold = "| Feature | A |\n|---|---|\n| write-ahead | |\n"
    got = "<table><tr><td>Feature</td><td>A</td></tr><tr><td>write- ahead</td><td>•</td></tr></table>"
    scores = element_gold.score(gold, got, [], set())
    assert scores["table_rows_exact"] == 2 and scores["cells_broken_hyphen"] == 1


def test_a_less_than_sign_in_code_is_not_a_tag():
    text = ("```\nmain = getLine >>= \\s -> print s\nx <- readLn\nif (a < b && c > d) {}\n```\n"
            "<div class=\"note\">kept</div>")
    got = element_gold.plain(text)
    assert "readLn" in got and "b && c" in got and "kept" in got and "div" not in got


def test_a_letter_spaced_heading_is_found_as_the_assembler_finds_it():
    got = element_gold.score("# Introduction\n\ntext", "# I n t r o d u c t i o n\n\ntext", [], set())
    assert (got["headings_found"], got["headings_phantom"]) == (1, 0)
