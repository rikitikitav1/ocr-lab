import text_layer
from stages.structure.sources import printed_contents


def _line(text, x, top, size=10.0):
    return text_layer.Line(text, x, top, size, True)


def test_rows_run_together_after_a_mark_split_when_their_numbers_rise_and_a_dash_between_numbers_is_no_mark():
    lines = [_line("1 Getting to know Redis 3", 115, 10, 13.0), _line("1.1 What is Redis? 4", 149, 20, 11.0),
             _line("Redis compared to other databases 4 ■ Other", 162, 30),
             _line("features 6 ■ Why Redis? 6", 161, 40),
             _line("Strings in Redis 9 ■ Lists in Redis 10 ■ Sets in Redis 11", 163, 50),
             _line("Hashes in Redis 12 ■ Sorted sets in Redis 13", 162, 60),
             _line("Gamma 15 ■ Delta 14", 162, 65),
             _line("2 Anatomy of a Redis web application 24", 104, 70, 13.0)]
    parsed, _ = printed_contents.parse([5], {5: lines}, 300)
    got = [(e.title, e.printed) for e, _, _ in parsed]
    assert got == [("1 Getting to know Redis", "3"), ("1.1 What is Redis?", "4"),
                   ("Redis compared to other databases", "4"), ("Other features", "6"), ("Why Redis?", "6"),
                   ("Strings in Redis", "9"), ("Lists in Redis", "10"), ("Sets in Redis", "11"),
                   ("Hashes in Redis", "12"), ("Sorted sets in Redis", "13"), ("Gamma 15 ■ Delta", "14"),
                   ("2 Anatomy of a Redis web application", "24")]
    ranges = [_line(f"Articles {a} – {a + 9} {a + 2}", 30, 10 * a) for a in range(1, 60, 10)]
    parsed, _ = printed_contents.parse([5], {5: ranges}, 300)
    assert [e.title for e, _, _ in parsed][0] == "Articles 1 – 10"


def test_a_row_out_as_title_lines_then_its_label_then_its_page_is_one_entry_and_the_page_s_folio_still_drops():
    lines = [_line("I. Introduction 13", 135, 10), _line("A. Connecting IP with Climate Change 13", 157, 20),
             _line("Background: International Legal Framework for Climate", 158, 30), _line("Change", 158, 40),
             _line("III.", 135, 50), _line("21", 451, 50),
             _line("2. Agenda 21 (1992) 21", 174, 60),
             _line("3. Convention on Biological Diversity (1993) 21", 175, 70),
             _line("9", 456, 80)]
    parsed, _ = printed_contents.parse([5], {5: lines}, 300)
    got = [(e.title, e.printed, line.x) for e, line, _ in parsed]
    assert got == [("I. Introduction", "13", 0), ("A. Connecting IP with Climate Change", "13", 22),
                   ("III. Background: International Legal Framework for Climate Change", "21", 0),
                   ("2. Agenda 21 (1992)", "21", 39), ("3. Convention on Biological Diversity (1993)", "21", 40)]
