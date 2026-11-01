from document.model import PageMarker, Paragraph
from elements import geometry


def test_a_reading_with_no_page_marker_has_no_spans_and_each_marker_runs_to_the_next():
    text = Paragraph(text="words")
    assert geometry.page_spans([]) == [] and geometry.page_spans([text]) == []
    first = PageMarker(book_page=1, file_ord=0, file_page=1)
    second = PageMarker(book_page=2, file_ord=0, file_page=2)
    assert geometry.page_spans([first, text, second, text]) == [(0, 2), (2, 4)]
