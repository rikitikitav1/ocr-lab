from stages import eta


class _Book:
    def __init__(self, pages, without=()):
        self.pages, self.text_layer = pages, {"without_layer": list(without), "garbled": []}


def test_a_kind_without_runs_is_unknown_and_a_known_one_is_its_pages_times_the_cost():
    text_only = {"text": eta._spread([1.0, 2.0, 3.0]), "scan": None}
    assert eta._seconds(_Book(100), text_only, "median") == 200
    assert eta._seconds(_Book(100, range(1, 61)), text_only, "median") is None
    assert eta._seconds(_Book(100), {"text": None, "scan": None}, "median") is None
