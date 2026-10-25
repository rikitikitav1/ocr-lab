from document.model import Caption, Figure, PageMarker, Paragraph
from elements import figures


def test_a_figure_takes_the_caption_by_it_on_its_page_and_each_caption_once():
    first, second = Figure(image="a.png"), Figure(image="b.png")
    blocks = [PageMarker(book_page=1, file_ord=0, file_page=1), first, Caption(text="Figure 1 A"), second,
              PageMarker(book_page=2, file_ord=0, file_page=2), Caption(text="Figure 2 B"), Paragraph(text="body")]
    out, n = figures.captioned(blocks)
    assert n == 1 and out[1].caption == "Figure 1 A" and out[3].caption is None


def test_a_caption_claimed_as_a_running_head_is_no_figure_s_caption():
    blocks = [Figure(image="a.png"), Caption(text="CHAPTER 3", slot="repeat")]
    assert figures.captioned(blocks) == (blocks, 0)
