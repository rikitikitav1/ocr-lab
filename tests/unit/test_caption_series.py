import text_layer
from document.model import Caption, Figure, Heading, PageMarker, Paragraph
from elements import captions


def _line(text, top, size=10.0, bold=False, x=50.0, right=400.0):
    return text_layer.Line(text, x, top, size, False, False, size, bold, right)


def _page(n, caption, body_after=True):
    lines = [_line("body text of the page that runs on in its column", 100), _line("more of the body text here", 112)]
    lines.append(_line(caption, 400, bold=True))
    if body_after:
        lines.append(_line("the next paragraph of the body goes on", 500))
    return lines


def test_a_numbered_series_by_drawings_is_learned_and_a_theorem_head_with_none_is_not():
    pages = {n: _page(n, f"Figure {n}.1 A diagram of part {n} of the system") for n in range(1, 7)}
    drawn = {n: [(50.0, 200.0, 400.0, 380.0)] for n in range(1, 7)}
    got = captions.learn(pages, drawings=lambda page: drawn.get(page, []))
    assert got[3] == ["Figure 3.1 A diagram of part 3 of the system"]
    heads = {n: _page(n, f"Theorem {n}.1 A statement we need here") for n in range(1, 7)}
    assert captions.learn(heads, drawings=lambda page: []) == {}


def test_a_paragraph_opening_with_its_caption_is_cut_after_it_and_a_pinned_heading_stays():
    marker = PageMarker(book_page=3, file_ord=0, file_page=3)
    caps = {3: ["Figure 3.1 A diagram of the system"]}
    picture = Figure(image="images/03-001.png", alt="")
    blocks = [marker, picture, Paragraph(text="Figure 3.1 A diagram of the system The text that follows the figure."),
              Heading(text="Figure 3.1 A diagram of the system", level=2, level_source="docling", node=4)]
    out, n = captions.series_captions(blocks, caps)
    assert n == 1 and isinstance(out[2], Caption) and out[2].text == "Figure 3.1 A diagram of the system"
    assert out[3].text == "The text that follows the figure." and isinstance(out[4], Heading)
    alone = [marker, Paragraph(text="Figure 3.1 A diagram of the system as the text names it")]
    assert captions.series_captions(alone, caps)[1] == 0


def test_a_caption_an_engine_set_aside_comes_back_after_its_picture():
    from types import SimpleNamespace

    marker = PageMarker(book_page=9, file_ord=0, file_page=5)
    picture = Figure(image="images/05-001.png", alt="")
    caption = "Figure 5.1 A marble kore from the Acropolis"
    read = SimpleNamespace(furniture_at=[(5, "aside_text", caption), (5, "header", "THE WHOLE ART")])
    out, n = captions.captions_from_furniture([marker, picture, Paragraph(text="body")], {"mineru": read},
                                            {5: {"picked": "mineru"}}, {9: [caption]})
    assert n == 1 and isinstance(out[2], Caption) and out[2].text == caption and out[3].text == "body"


# the pass runs inside the range passes, where the book's captions arrive as an argument of the same name
def test_the_range_passes_bring_a_set_aside_caption_back_when_the_caption_series_is_on():
    from types import SimpleNamespace

    from assembly import passes

    caption = "Figure 5.1 A marble kore from the Acropolis"
    blocks = [PageMarker(book_page=9, file_ord=0, file_page=5), Figure(image="images/05-001.png", alt="")]
    read = SimpleNamespace(blocks=blocks, furniture_at=[(5, "aside_text", caption)])
    out, counts = passes.apply({"mineru": read}, {5: ""}, lambda page: [], ("mineru",),
                               knobs={"caption_series": True}, captions={9: [caption]})
    assert counts["captions_from_furniture"] == 1 and isinstance(out[-1], Caption)

