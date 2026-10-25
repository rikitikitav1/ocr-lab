from elements import code

W, H = 0.01, 0.02


def row(text, y, x0=0.1):
    return [(x0 + i * W, y, x0 + (i + 1) * W, y + H, c) for i, c in enumerate(text) if c != " "]


def test_rows_spaces_and_indent_come_from_the_advance():
    glyphs = row("def f(x):", 0.1) + row("    return x", 0.13)
    assert code.rebuild(glyphs, (0.0, 0.05, 0.9, 0.2), set()) == "def f(x):\n    return x"


def test_a_proportional_face_keeps_the_engine_text():
    glyphs = [(0.1, 0.1, 0.11, 0.12, "i"), (0.11, 0.1, 0.14, 0.12, "m"), (0.14, 0.1, 0.15, 0.12, "l"),
              (0.15, 0.1, 0.19, 0.12, "W")]
    assert code.rebuild(glyphs, (0.0, 0.05, 0.9, 0.2), set()) is None


def test_a_row_cut_by_a_short_box_runs_on_and_is_given_once():
    glyphs = row("SELECT * FROM t;", 0.1)
    taken = set()
    assert code.rebuild(glyphs, (0.0, 0.05, 0.15, 0.2), taken) == "SELECT * FROM t;"
    assert code.rebuild(glyphs, (0.0, 0.05, 0.9, 0.2), taken) == ""


def test_listing_numbers_go_when_every_row_has_one():
    glyphs = row("1 a = 1", 0.1) + row("2 b = 2", 0.13) + row("3 c = 3", 0.16)
    assert code.rebuild(glyphs, (0.0, 0.05, 0.9, 0.3), set()) == "a = 1\nb = 2\nc = 3"


def test_a_gap_of_a_row_between_rows_is_a_blank_line():
    glyphs = row(">>> a = 1", 0.1) + row(">>> b = 2", 0.13) + row(">>> c = 3", 0.19)
    assert code.rebuild(glyphs, (0.0, 0.05, 0.9, 0.3), set()) == ">>> a = 1\n>>> b = 2\n\n>>> c = 3"


def test_a_paragraph_set_in_one_advance_becomes_code_but_prose_does_not():
    from document.model import Code, Paragraph, Where

    where = Where(page=1, box=(0.0, 0.05, 0.9, 0.2), engine="mineru")
    command = Paragraph(text="$ git init", where=where)
    assert isinstance(code.mono_paragraphs([command], lambda p: row("$ git init --bare", 0.1))[0][0], Code)
    prose = [(0.1, 0.1, 0.11, 0.12, "i"), (0.11, 0.1, 0.14, 0.12, "m"), (0.14, 0.1, 0.15, 0.12, "l"),
             (0.15, 0.1, 0.19, 0.12, "W"), (0.19, 0.1, 0.2, 0.12, "i"), (0.2, 0.1, 0.24, 0.12, "m"),
             (0.24, 0.1, 0.25, 0.12, "l"), (0.25, 0.1, 0.29, 0.12, "W")]
    assert isinstance(code.mono_paragraphs([Paragraph(text="imlW", where=where)], lambda p: prose)[0][0], Paragraph)


def test_a_one_row_term_in_one_advance_stays_prose_unless_it_reads_as_a_command():
    from document.model import Code, Paragraph, Where

    where = Where(page=1, box=(0.0, 0.05, 0.9, 0.2), engine="mineru")
    term = Paragraph(text="auto_explain.log_wal(boolean)", where=where)
    assert isinstance(code.mono_paragraphs([term], lambda p: row("auto_explain.log_wal(boolean)", 0.1))[0][0],
                      Paragraph)
    url = Paragraph(text="• ftp://ftp.tex.ac.uk/tex-archive/", where=where)
    two_rows = row("• ftp://ftp.tex.ac.uk/", 0.1) + row("tex-archive/", 0.13)
    assert isinstance(code.mono_paragraphs([url], lambda p: two_rows)[0][0], Paragraph)
    select = Paragraph(text="SELECT * FROM pg_user;", where=where)
    assert isinstance(code.mono_paragraphs([select], lambda p: row("SELECT * FROM pg_user;", 0.1))[0][0], Code)


def test_a_code_box_the_other_engine_drew_replaces_the_prose_inside_it():
    from document.model import Code, PageMarker, Paragraph, Where

    def at(engine, top, bottom):
        return Where(page=1, box=(0.1, top, 0.9, bottom), engine=engine)

    chosen = [PageMarker(book_page=1, file_ord=0, file_page=1), Paragraph(text="before", where=at("d", 0.1, 0.15)),
              Paragraph(text="$ git init", where=at("d", 0.3, 0.33)), Paragraph(text="after", where=at("d", 0.6, 0.7))]
    other = [Code(text="$ git init", where=at("m", 0.28, 0.35)), Code(text="$ lost", where=at("m", 0.45, 0.5))]
    mono = row("$ git init", 0.29) + row("$ lost", 0.46)
    out, added = code.code_union(chosen, [other], lambda page: mono)
    assert added == 2 and [type(b).__name__ + ":" + getattr(b, "text", "") for b in out[1:]] == [
        "Paragraph:before", "Code:$ git init", "Code:$ lost", "Paragraph:after"]


def test_a_code_block_cut_by_the_page_is_joined_but_two_blocks_mid_page_are_not():
    from document.model import Code, PageMarker, Where

    low = Code(text="SELECT a,", where=Where(page=1, box=(0.1, 0.8, 0.9, 0.95), engine="d"))
    high = Code(text="       b FROM t;", where=Where(page=2, box=(0.1, 0.05, 0.9, 0.1), engine="d"))
    out, n = code.join_code_across_pages([low, PageMarker(book_page=2, file_ord=0, file_page=2), high])
    assert n == 1 and out[0].text == "SELECT a,\n       b FROM t;" and len(out) == 2
    mid = Code(text="x", where=Where(page=1, box=(0.1, 0.4, 0.9, 0.5), engine="d"))
    assert code.join_code_across_pages([mid, PageMarker(book_page=2, file_ord=0, file_page=2), high])[1] == 0


def test_a_space_the_layer_holds_stays_where_a_bold_glyph_leaves_less_than_a_cell():
    bold = [(*g, False) for g in row("SELECT", 0.1)]
    name = [(x0 - 0.7 * W, y0, x1 - 0.7 * W, y1, c, i == 0)
            for i, (x0, y0, x1, y1, c) in enumerate(row("       Name;", 0.1))]
    glyphs = [*bold, *name, *[(*g, False) for g in row("FROM t;", 0.13)]]
    assert code.rebuild(glyphs, (0.0, 0.05, 0.9, 0.2), set()) == "SELECT Name;\nFROM t;"
    unspaced = [*bold, *[(*g[:5], False) for g in name]]
    assert code.rebuild(unspaced, (0.0, 0.05, 0.9, 0.2), set()) == "SELECTName;"


def test_a_code_fragment_inside_the_listing_next_to_it_goes_but_a_snippet_apart_stays():
    from document.model import Code, Where

    def block(text, box):
        return Code(text=text, where=Where(page=1, box=box, engine="m"))

    whole = block("foo() {\n  local val=${1:?give an argument}\n}", (0.1, 0.1, 0.3, 0.2))
    fragment = block("val=${1:?give an argument}", (0.18, 0.13, 0.4, 0.15))
    apart = block("val=${1:?give an argument}", (0.1, 0.5, 0.3, 0.52))
    closing = block("fi", (0.1, 0.19, 0.12, 0.2))
    out, dropped = code.drop_code_fragments([fragment, whole, closing, apart])
    assert out == [whole, closing, apart] and dropped == 1


def test_a_listing_s_line_numbers_are_counted_and_a_lone_number_or_a_year_is_not():
    layer = ("1 void Update() {\n2   for (e : all) {\n3     e.tick();\n4   }\n"
             "In 1998 the engine\nwas rewritten from scratch\n7 days later\n")
    assert code.listing_numbers(layer) == {"1": 1, "2": 1, "3": 1, "4": 1}
    wrapped = "10 SELECT name,\n   price FROM items\n20 WHERE price > 3\n30 ORDER BY name;\n40 LIMIT 5;\n"
    assert code.listing_numbers(wrapped) == {"10": 1, "20": 1, "30": 1, "40": 1}
    assert code.listing_numbers("Prose about 3 things.\nMore prose here\nAnd 1998 came.\n") == {}
