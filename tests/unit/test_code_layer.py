from assembly import code_layer

W, H = 0.01, 0.02


def row(text, y, x0=0.1):
    return [(x0 + i * W, y, x0 + (i + 1) * W, y + H, c) for i, c in enumerate(text) if c != " "]


def test_rows_spaces_and_indent_come_from_the_advance():
    glyphs = row("def f(x):", 0.1) + row("    return x", 0.13)
    assert code_layer.rebuild(glyphs, (0.0, 0.05, 0.9, 0.2), set()) == "def f(x):\n    return x"


def test_a_proportional_face_keeps_the_engine_text():
    glyphs = [(0.1, 0.1, 0.11, 0.12, "i"), (0.11, 0.1, 0.14, 0.12, "m"), (0.14, 0.1, 0.15, 0.12, "l"),
              (0.15, 0.1, 0.19, 0.12, "W")]
    assert code_layer.rebuild(glyphs, (0.0, 0.05, 0.9, 0.2), set()) is None


def test_a_row_cut_by_a_short_box_runs_on_and_is_given_once():
    glyphs = row("SELECT * FROM t;", 0.1)
    taken = set()
    assert code_layer.rebuild(glyphs, (0.0, 0.05, 0.15, 0.2), taken) == "SELECT * FROM t;"
    assert code_layer.rebuild(glyphs, (0.0, 0.05, 0.9, 0.2), taken) == ""


def test_listing_numbers_go_when_every_row_has_one():
    glyphs = row("1 a = 1", 0.1) + row("2 b = 2", 0.13) + row("3 c = 3", 0.16)
    assert code_layer.rebuild(glyphs, (0.0, 0.05, 0.9, 0.3), set()) == "a = 1\nb = 2\nc = 3"


def test_a_gap_of_a_row_between_rows_is_a_blank_line():
    glyphs = row(">>> a = 1", 0.1) + row(">>> b = 2", 0.13) + row(">>> c = 3", 0.19)
    assert code_layer.rebuild(glyphs, (0.0, 0.05, 0.9, 0.3), set()) == ">>> a = 1\n>>> b = 2\n\n>>> c = 3"


def test_a_table_takes_the_preferred_grid_at_its_place_unless_that_engine_split_it():
    from assembly import passes
    from document.model import Cell, Table, Where

    def table(engine, top, text):
        return Table(rows=[[Cell(text=text)]], where=Where(page=1, box=(0.1, top, 0.9, top + 0.2), engine=engine))

    ours = [table("docling", 0.1, "docling grid")]
    assert passes.tables_from(ours, [table("mineru", 0.12, "mineru grid")])[0][0].rows[0][0].text == "mineru grid"
    split = [table("mineru", 0.1, "a"), table("mineru", 0.15, "b")]
    assert passes.tables_from(ours, split)[0][0].rows[0][0].text == "docling grid"


def test_a_table_takes_the_grid_that_agrees_with_the_layer_words_in_its_box():
    from assembly import passes
    from document.model import Cell, Table, Where

    def table(engine, texts):
        return Table(rows=[[Cell(text=t) for t in texts]], where=Where(page=1, box=(0.0, 0.0, 1.0, 0.5), engine=engine))

    layer = row("alpha beta gamma", 0.1)
    full, short = table("docling", ["alpha", "beta", "gamma"]), table("mineru", ["alpha", "beta"])
    assert passes.tables_by_layer([full], [short], lambda page: layer)[0][0].where.engine == "docling"
    assert passes.tables_by_layer([short.model_copy(update={"where": full.where})],
                                  [table("mineru", ["alpha", "beta", "gamma"])], lambda page: layer)[1] == 1


def test_a_paragraph_set_in_one_advance_becomes_code_but_prose_does_not():
    from assembly import passes
    from document.model import Code, Paragraph, Where

    where = Where(page=1, box=(0.0, 0.05, 0.9, 0.2), engine="mineru")
    command = Paragraph(text="$ git init", where=where)
    assert isinstance(passes.mono_paragraphs([command], lambda p: row("$ git init --bare", 0.1))[0][0], Code)
    prose = [(0.1, 0.1, 0.11, 0.12, "i"), (0.11, 0.1, 0.14, 0.12, "m"), (0.14, 0.1, 0.15, 0.12, "l"),
             (0.15, 0.1, 0.19, 0.12, "W"), (0.19, 0.1, 0.2, 0.12, "i"), (0.2, 0.1, 0.24, 0.12, "m"),
             (0.24, 0.1, 0.25, 0.12, "l"), (0.25, 0.1, 0.29, 0.12, "W")]
    assert isinstance(passes.mono_paragraphs([Paragraph(text="imlW", where=where)], lambda p: prose)[0][0], Paragraph)


def test_a_one_row_term_in_one_advance_stays_prose_unless_it_reads_as_a_command():
    from assembly import passes
    from document.model import Code, Paragraph, Where

    where = Where(page=1, box=(0.0, 0.05, 0.9, 0.2), engine="mineru")
    term = Paragraph(text="auto_explain.log_wal(boolean)", where=where)
    assert isinstance(passes.mono_paragraphs([term], lambda p: row("auto_explain.log_wal(boolean)", 0.1))[0][0],
                      Paragraph)
    url = Paragraph(text="• ftp://ftp.tex.ac.uk/tex-archive/", where=where)
    two_rows = row("• ftp://ftp.tex.ac.uk/", 0.1) + row("tex-archive/", 0.13)
    assert isinstance(passes.mono_paragraphs([url], lambda p: two_rows)[0][0], Paragraph)
    select = Paragraph(text="SELECT * FROM pg_user;", where=where)
    assert isinstance(passes.mono_paragraphs([select], lambda p: row("SELECT * FROM pg_user;", 0.1))[0][0], Code)


def test_a_code_box_the_other_engine_drew_replaces_the_prose_inside_it():
    from assembly import passes
    from document.model import Code, PageMarker, Paragraph, Where

    def at(engine, top, bottom):
        return Where(page=1, box=(0.1, top, 0.9, bottom), engine=engine)

    chosen = [PageMarker(book_page=1, file_ord=0, file_page=1), Paragraph(text="before", where=at("d", 0.1, 0.15)),
              Paragraph(text="$ git init", where=at("d", 0.3, 0.33)), Paragraph(text="after", where=at("d", 0.6, 0.7))]
    other = [Code(text="$ git init", where=at("m", 0.28, 0.35)), Code(text="$ lost", where=at("m", 0.45, 0.5))]
    mono = row("$ git init", 0.29) + row("$ lost", 0.46)
    out, added = passes.code_union(chosen, [other], lambda page: mono)
    assert added == 2 and [type(b).__name__ + ":" + getattr(b, "text", "") for b in out[1:]] == [
        "Paragraph:before", "Code:$ git init", "Code:$ lost", "Paragraph:after"]


def test_a_grid_that_drops_the_layer_s_check_marks_loses():
    from assembly import passes
    from document.model import Cell, Table, Where

    where = Where(page=1, box=(0.0, 0.0, 1.0, 0.5), engine="docling")
    layer = row("sync • •", 0.1)
    marked = Table(rows=[[Cell(text="sync"), Cell(text="•"), Cell(text="•")]], where=where)
    plain = Table(rows=[[Cell(text="sync"), Cell(text=""), Cell(text="")]],
                  where=where.model_copy(update={"engine": "mineru"}))
    assert passes.tables_by_layer([marked], [plain], lambda page: layer)[0][0].where.engine == "docling"


def test_a_table_only_the_other_engine_drew_replaces_the_prose_it_covers():
    from assembly import passes
    from document.model import Cell, PageMarker, Paragraph, Table, Where

    def at(engine, top, bottom):
        return Where(page=1, box=(0.0, top, 1.0, bottom), engine=engine)

    chosen = [PageMarker(book_page=1, file_ord=0, file_page=1),
              Paragraph(text="usename name", where=at("d", 0.1, 0.12)),
              Paragraph(text="after", where=at("d", 0.6, 0.7))]
    table = Table(rows=[[Cell(text="usename")], [Cell(text="name")]], where=at("m", 0.05, 0.2))
    out, added = passes.table_union(chosen, [table], lambda page: row("usename name", 0.1))
    assert added == 1 and [type(b).__name__ for b in out[1:]] == ["Table", "Paragraph"]
    assert passes.table_union(chosen, [table], lambda page: row("something else entirely here", 0.1))[1] == 0


def test_a_code_block_cut_by_the_page_is_joined_but_two_blocks_mid_page_are_not():
    from assembly import passes
    from document.model import Code, PageMarker, Where

    low = Code(text="SELECT a,", where=Where(page=1, box=(0.1, 0.8, 0.9, 0.95), engine="d"))
    high = Code(text="       b FROM t;", where=Where(page=2, box=(0.1, 0.05, 0.9, 0.1), engine="d"))
    out, n = passes.join_code_across_pages([low, PageMarker(book_page=2, file_ord=0, file_page=2), high])
    assert n == 1 and out[0].text == "SELECT a,\n       b FROM t;" and len(out) == 2
    mid = Code(text="x", where=Where(page=1, box=(0.1, 0.4, 0.9, 0.5), engine="d"))
    assert passes.join_code_across_pages([mid, PageMarker(book_page=2, file_ord=0, file_page=2), high])[1] == 0


def test_a_space_the_layer_holds_stays_where_a_bold_glyph_leaves_less_than_a_cell():
    bold = [(*g, False) for g in row("SELECT", 0.1)]
    name = [(x0 - 0.7 * W, y0, x1 - 0.7 * W, y1, c, i == 0)
            for i, (x0, y0, x1, y1, c) in enumerate(row("       Name;", 0.1))]
    glyphs = [*bold, *name, *[(*g, False) for g in row("FROM t;", 0.13)]]
    assert code_layer.rebuild(glyphs, (0.0, 0.05, 0.9, 0.2), set()) == "SELECT Name;\nFROM t;"
    unspaced = [*bold, *[(*g[:5], False) for g in name]]
    assert code_layer.rebuild(unspaced, (0.0, 0.05, 0.9, 0.2), set()) == "SELECTName;"


def test_a_code_fragment_inside_the_listing_next_to_it_goes_but_a_snippet_apart_stays():
    from assembly import passes
    from document.model import Code, Where

    def code(text, box):
        return Code(text=text, where=Where(page=1, box=box, engine="m"))

    whole = code("foo() {\n  local val=${1:?give an argument}\n}", (0.1, 0.1, 0.3, 0.2))
    fragment = code("val=${1:?give an argument}", (0.18, 0.13, 0.4, 0.15))
    apart = code("val=${1:?give an argument}", (0.1, 0.5, 0.3, 0.52))
    closing = code("fi", (0.1, 0.19, 0.12, 0.2))
    out, dropped = passes.drop_code_fragments([fragment, whole, closing, apart])
    assert out == [whole, closing, apart] and dropped == 1
