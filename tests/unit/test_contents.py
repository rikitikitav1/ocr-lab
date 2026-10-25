from document.model import Heading, ListBlock, ListItem, PageMarker, Paragraph
from elements import contents


def _page(n):
    return PageMarker(book_page=n, file_ord=0, file_page=n)


def test_a_chapter_s_section_list_becomes_one_contents_block_and_a_chain_of_headings_does_not():
    from document.model import Contents, Paragraph

    nodes = [{"title": "1 Systems", "level": 1, "first_page": 1}, {"title": "1.1 Introduction", "level": 2},
             {"title": "1.2 Examples", "level": 2}, {"title": "1.3 Trends", "level": 2}]
    rows = "SYSTEMS\n1.1 Introduction\n1.2 Examples\n1.3 Trends\nA distributed system is one in which components"
    blocks = [_page(1), Paragraph(text="1.1 Introduction"), Paragraph(text="1.2 Examples"),
              Paragraph(text="1.3 Trends"), Paragraph(text="A distributed system is one in which components"), _page(2),
              Heading(text="1.1 Introduction", level=2, level_source="docling")]
    out, n = contents.chapter_contents(blocks, nodes, {1: rows})
    assert n == 1 and isinstance(out[1], Contents) and out[1].entries == ["1.1 Introduction", "1.2 Examples",
                                                                          "1.3 Trends"]
    assert isinstance(out[-1], Heading)
    chain = [{"title": "2 Law", "level": 1, "first_page": 1}, {"title": "A. Basis", "level": 2},
             {"title": "1. Pledge", "level": 3}, {"title": "a) Scope", "level": 4}]
    assert contents.chapter_contents(blocks, chain, {1: "A. Basis\n1. Pledge\na) Scope\nText"})[1] == 0


def test_a_contents_list_with_nested_items_keeps_every_line_in_the_contents_block():
    from document.model import Contents

    nodes = [{"title": "1 Systems", "level": 1, "first_page": 1}, {"title": "1.1 Introduction", "level": 2},
             {"title": "1.1.1 Scope", "level": 3}, {"title": "1.2 Examples", "level": 2},
             {"title": "1.3 Trends", "level": 2}]
    rows = "SYSTEMS\n1.1 Introduction\n1.1.1 Scope\n1.2 Examples\n1.3 Trends\nA distributed system is one"
    nested = ListBlock(ordered=False, items=[ListItem(text="1.1.1 Scope")])
    listed = ListBlock(ordered=False, items=[ListItem(text="1.1 Introduction", children=[nested]),
                                             ListItem(text="1.2 Examples"),
                              ListItem(text="1.3 Trends")])
    blocks = [_page(1), listed, Paragraph(text="A distributed system is one")]
    out, n = contents.chapter_contents(blocks, nodes, {1: rows})
    assert n == 1 and isinstance(out[1], Contents)
    assert out[1].entries == ["1.1 Introduction", "1.1.1 Scope", "1.2 Examples", "1.3 Trends"]


def test_a_contents_row_drops_its_page_arabic_or_roman_after_a_leader_and_a_title_keeps_its_numeral():
    assert contents._entry("1.1 Introduction ..... xv") == contents._entry("1.1 Introduction 12") == "introduction"
    assert contents._entry("World War II") == "world war ii"
