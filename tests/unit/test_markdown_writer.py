import pytest
from document.model import (
    Caption,
    Cell,
    Chapter,
    Code,
    Document,
    Figure,
    Heading,
    ListBlock,
    ListItem,
    Note,
    Paragraph,
    Table,
)
from writers import markdown


def _book(*chapters):
    return markdown.document(Document(title="The Book", chapters=list(chapters)))


def test_title_chapters_parts_and_inner_headings_take_their_levels():
    out = _book(Chapter(ord=1, title="Part One", level=1, first_page=3, last_page=40),
                Chapter(ord=2, title="Chapter 1", level=2, first_page=4, last_page=40,
                        blocks=[Heading(text="A section", level=1, level_source="toc")]))
    assert out.startswith("# The Book\n")
    assert "\n## Part One\n" in out and "\n### Chapter 1\n" in out and "\n#### A section\n" in out
    assert "<!-- chapter ord=2 pages=4-40 role=body -->" in out


def test_a_heading_past_level_six_is_refused_not_clipped():
    with pytest.raises(markdown.LevelTooDeep):
        _book(Chapter(ord=1, title="Deep", level=3, first_page=1, last_page=2,
                      blocks=[Heading(text="Too deep", level=3, level_source="engine")]))


def test_code_keeps_its_indent_and_a_fence_inside_it():
    code = "def f():\n    return '```'\n\n    pass\n"
    out = _book(Chapter(ord=1, title="C", level=1, first_page=1, last_page=1,
                        blocks=[Code(text=code, language="python")]))
    assert "````python\ndef f():\n    return '```'\n\n    pass\n````" in out


def test_tables_are_pipe_tables_unless_cells_are_merged():
    simple = Table(rows=[[Cell(text="a|b", header=True), Cell(text="c")], [Cell(text="1"), Cell(text="2")]])
    merged = Table(rows=[[Cell(text="wide", colspan=2)], [Cell(text="1"), Cell(text="2")]])
    out = _book(Chapter(ord=1, title="T", level=1, first_page=1, last_page=1, blocks=[simple, merged]))
    assert "| a\\|b | c |\n|---|---|\n| 1 | 2 |" in out
    assert '<td colspan="2">wide</td>' in out


def test_lists_keep_their_type_and_nesting():
    lst = ListBlock(ordered=True, items=[ListItem(text="one", children=[ListBlock(ordered=False, items=[
        ListItem(text="inner")])]), ListItem(text="two")])
    out = _book(Chapter(ord=1, title="L", level=1, first_page=1, last_page=1, blocks=[lst]))
    assert "1. one\n   - inner\n2. two" in out


def test_notes_are_quotes_and_prose_never_turns_into_syntax():
    out = _book(Chapter(ord=1, title="N", level=1, first_page=1, last_page=1, blocks=[
        Note(label="Совет", text="Keep it short.\nReally."),
        Paragraph(text="# not a heading\n1. not a list"),
        Figure(image="images/01-001.png", alt="A cat"), Caption(text="Figure 1. A cat")]))
    assert "> **Совет:** Keep it short.\n> Really." in out
    assert "\\# not a heading\n1\\. not a list" in out
    assert "![A cat](images/01-001.png)\n\n*Figure 1. A cat*" in out


def test_a_figure_without_a_kept_image_is_marked_not_linked():
    from document.model import Where

    out = markdown.chapter(Chapter(ord=1, title="T", level=1, first_page=1, last_page=1, blocks=[
        Figure(image="#/pictures/0", where=Where(page=3, box=(0, 0, 1, 1), engine="docling"))]))
    assert "<!-- figure page 3: image not kept yet -->" in out and "](#/pictures" not in out
