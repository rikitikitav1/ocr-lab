from stages import result_run


def test_the_result_run_loses_least_text_then_finds_most_sections_then_doubles_least_then_adds_least():
    runs = {1: {"lost_text": 0.02, "subs": 100, "subs_found": 90, "extra_text": 0.01},
            2: {"lost_text": 0.01, "subs": 100, "subs_found": 80, "extra_text": 0.05},
            3: {"lost_text": 0.01, "subs": 19, "subs_found": 1, "duplicates": 0, "extra_text": 0.0},
            4: {"lost_text": 0.01, "subs": 12, "subs_found": 2, "duplicates": 6, "extra_text": 0.0},
            5: {"lost_text": 0.01, "subs": 100, "subs_found": 85, "duplicates": 1, "extra_text": 0.02},
            6: {"lost_text": 0.01, "subs": 100, "subs_found": 85, "duplicates": 1, "extra_text": 0.02},
            7: {"lost_text": None, "subs": 10, "subs_found": 10, "extra_text": 0.0}}
    order = sorted(runs, key=lambda r: result_run.rank(r, runs[r]))
    assert order == [6, 5, 2, 4, 3, 1, 7]
