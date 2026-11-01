from document.model import Caption, Cell, Figure, PageMarker, Paragraph, Table
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


def test_a_piece_that_captions_above_gives_a_figure_the_caption_above_though_one_follows():
    figs = [Figure(image=f"{i}.png") for i in range(3)]
    blocks = [Caption(text="Figure 1"), figs[0], Paragraph(text="body"), Caption(text="Figure 2"), figs[1],
              Caption(text="Figure 3"), figs[2]]
    out, n = figures.captioned(blocks)
    assert n == 3 and [out[i].caption for i in (1, 4, 6)] == ["Figure 1", "Figure 2", "Figure 3"]


def test_a_caption_two_blocks_off_on_the_figure_s_page_is_its_own():
    blocks = [Figure(image="a.png"), Paragraph(text="(a) the left part"), Caption(text="Figure 4 Both parts")]
    assert figures.captioned(blocks)[0][0].caption == "Figure 4 Both parts"


def test_a_table_between_keeps_its_caption_from_the_figure():
    blocks = [Figure(image="a.png"), Table(rows=[[Cell(text="a")]]), Caption(text="Table 1. Sizes")]
    out, n = figures.captioned(blocks)
    assert n == 0 and out[0].caption is None
