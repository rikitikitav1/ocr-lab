from evaluation import structure_gate


def test_a_structure_gate_names_what_moved_and_leaves_an_unmoved_book_out():
    base = {"1": {"source": "bookmarks", "entries": [["One", 1, 3], ["Two", 1, 9]]},
            "2": {"source": "printed_contents", "entries": [["A", 1, 5]]}, "3": {"skipped": "WrongLane"}}
    new = {"1": {"source": "bookmarks", "entries": [["One", 1, 3], ["Two", 2, 9]]},
           "2": {"source": "printed_contents", "entries": [["A", 1, 5]]}, "3": {"failed": "no structure"}}
    moved, lines = structure_gate.compare(base, new)
    assert moved == 2 and lines[-1] == "books moved: 2 of 3"
    assert lines[0].startswith("1 bookmarks -> bookmarks: 2 -> 2 entries, gone 1 ['Two (1, p9)'], added 1")
    assert lines[1] == "3 skipped -> failed: no structure"
