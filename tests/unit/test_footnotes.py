from document.model import PageMarker, Paragraph
from elements import footnotes


def _page(n):
    return PageMarker(book_page=n, file_ord=0, file_page=n)


def test_a_footnote_an_engine_set_aside_comes_back_at_its_page_s_end_where_the_layout_reads_a_note():
    from types import SimpleNamespace

    read = SimpleNamespace(furniture_at=[(1, "footer", "16 For discussion of these ideals see Duke, 2013."),
                                         (1, "page_number", "104"), (2, "footer", "16 For discussion of it")])
    blocks = [_page(1), Paragraph(text="body"), _page(2), Paragraph(text="more")]
    notes = {1: " 16 for discussion of these ideals see duke, 2013. 104 "}
    picked = {1: {"picked": "mineru"}, 2: {"picked": "mineru"}}
    got, n = footnotes.notes_from_furniture(blocks, {"mineru": read}, picked, notes)
    assert n == 1 and [getattr(b, "text", None) for b in got] == [
        None, "body", "16 For discussion of these ideals see Duke, 2013.", None, "more"]
