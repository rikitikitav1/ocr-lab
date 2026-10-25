from elements import captions
from text_layer import Line


def _line(text, x, top, size=10.0):
    return Line(text, x, top, size, False, head_size=size, right=x + 6 * len(text))


def test_a_caption_is_the_smaller_block_under_a_picture_and_body_text_under_it_is_not():
    body = [_line(f"body line {i}", 50, 400 + 12 * i) for i in range(20)]
    lines = {1: [_line("Figure 1. A fox", 60, 310, 8.0), _line("seen at night", 60, 320, 8.0)] + body,
             2: [_line("plain body under the picture", 60, 310)] + body}
    pictures = {1: [(50.0, 100.0, 300.0, 300.0)], 2: [(50.0, 100.0, 300.0, 300.0)]}
    assert captions.by_page(pictures, lines) == {1: ["Figure 1. A fox seen at night"]}


def test_a_caption_over_a_picture_is_found_when_none_stands_under_it():
    body = [_line(f"body line {i}", 50, 400 + 12 * i) for i in range(20)]
    lines = {1: [_line("Table 4. Sizes", 60, 80, 8.0)] + body}
    assert captions.by_page({1: [(50.0, 100.0, 300.0, 300.0)]}, lines) == {1: ["Table 4. Sizes"]}
