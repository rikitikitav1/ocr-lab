from structure import tree


def test_a_node_hangs_under_the_nearest_node_before_it_on_a_higher_level():
    assert tree.parents([1, 2, 3, 3, 2, 1, 3]) == [None, 0, 1, 1, 0, None, 5]


def test_a_level_skipped_still_finds_its_parent_and_the_depth_is_the_deepest_level():
    assert tree.parents([2, 4, 1]) == [None, 0, None]
    assert tree.depth([1, 2, 4, 2]) == 4
    assert tree.depth([]) == 0


def test_the_parent_is_the_nearest_node_before_on_a_higher_level_as_the_migration_reads_it():
    levels = [1, 3, 2, 4, 4, 1, 2, 2, 3, 1]
    nearest = [max((j for j in range(i) if levels[j] < level), default=None) for i, level in enumerate(levels)]
    assert tree.parents(levels) == nearest


def test_a_node_no_unit_holds_goes_with_the_unit_opening_on_its_page_and_no_other():
    from stages import run_pieces

    units = [{"ord": 2, "first_page": 10, "nodes": [{"ord": 2}, {"ord": 3}]}, {"ord": 5, "first_page": 40,
                                                                           "nodes": [{"ord": 5}]}]
    assert run_pieces.holding(units, 3, 12)["ord"] == 2
    assert run_pieces.holding(units, 1, 10)["ord"] == 2
    assert run_pieces.holding(units, 4, 39) is None
