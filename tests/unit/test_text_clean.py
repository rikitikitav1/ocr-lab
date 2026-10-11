import text_clean


def test_invisible_and_control_characters_go_and_odd_spaces_become_plain():
    assert text_clean.clean("о\xa0книге­ ​вер\x81сия﻿￾") == "о книге версия"


def test_unicode_ligatures_are_spelled_out_and_line_breaks_stay():
    assert text_clean.clean("Pathﬁnding\r\nshuﬄe\tcode") == "Pathfinding\r\nshuffle\tcode"


def test_private_use_characters_stay_since_a_font_may_keep_ligatures_there():
    assert text_clean.clean("Dierence") == "Dierence"


def test_cp1251_read_as_latin1_is_repaired_before_cleaning():
    import pdf

    assert pdf.repair("Áîãäàí\xa0Ñ") == "Богдан С"


def test_the_zero_width_joiners_farsi_spells_with_stay_and_a_zero_width_space_goes():
    assert text_clean.clean("می‌خواهم​") == "می‌خواهم"
