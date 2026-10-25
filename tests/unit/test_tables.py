from elements import tables

W, H = 0.01, 0.02


def row(text, y, x0=0.1):
    return [(x0 + i * W, y, x0 + (i + 1) * W, y + H, c) for i, c in enumerate(text) if c != " "]


def test_a_table_takes_the_preferred_grid_at_its_place_unless_that_engine_split_it():
    from document.model import Cell, Table, Where

    def table(engine, top, text):
        return Table(rows=[[Cell(text=text)]], where=Where(page=1, box=(0.1, top, 0.9, top + 0.2), engine=engine))

    ours = [table("docling", 0.1, "docling grid")]
    assert tables.tables_from(ours, [table("mineru", 0.12, "mineru grid")])[0][0].rows[0][0].text == "mineru grid"
    split = [table("mineru", 0.1, "a"), table("mineru", 0.15, "b")]
    assert tables.tables_from(ours, split)[0][0].rows[0][0].text == "docling grid"


def test_a_table_takes_the_grid_that_agrees_with_the_layer_words_in_its_box():
    from document.model import Cell, Table, Where

    def table(engine, texts):
        return Table(rows=[[Cell(text=t) for t in texts]], where=Where(page=1, box=(0.0, 0.0, 1.0, 0.5), engine=engine))

    layer = row("alpha beta gamma", 0.1)
    full, short = table("docling", ["alpha", "beta", "gamma"]), table("mineru", ["alpha", "beta"])
    assert tables.tables_by_layer([full], [short], lambda page: layer)[0][0].where.engine == "docling"
    assert tables.tables_by_layer([short.model_copy(update={"where": full.where})],
                                  [table("mineru", ["alpha", "beta", "gamma"])], lambda page: layer)[1] == 1


def test_a_grid_that_drops_the_layer_s_check_marks_loses():
    from document.model import Cell, Table, Where

    where = Where(page=1, box=(0.0, 0.0, 1.0, 0.5), engine="docling")
    layer = row("sync • •", 0.1)
    marked = Table(rows=[[Cell(text="sync"), Cell(text="•"), Cell(text="•")]], where=where)
    plain = Table(rows=[[Cell(text="sync"), Cell(text=""), Cell(text="")]],
                  where=where.model_copy(update={"engine": "mineru"}))
    assert tables.tables_by_layer([marked], [plain], lambda page: layer)[0][0].where.engine == "docling"


def test_a_table_only_the_other_engine_drew_replaces_the_prose_it_covers():
    from document.model import Cell, PageMarker, Paragraph, Table, Where

    def at(engine, top, bottom):
        return Where(page=1, box=(0.0, top, 1.0, bottom), engine=engine)

    chosen = [PageMarker(book_page=1, file_ord=0, file_page=1),
              Paragraph(text="usename name", where=at("d", 0.1, 0.12)),
              Paragraph(text="after", where=at("d", 0.6, 0.7))]
    table = Table(rows=[[Cell(text="usename")], [Cell(text="name")]], where=at("m", 0.05, 0.2))
    out, added = tables.table_union(chosen, [table], lambda page: row("usename name", 0.1))
    assert added == 1 and [type(b).__name__ for b in out[1:]] == ["Table", "Paragraph"]
    assert tables.table_union(chosen, [table], lambda page: row("something else entirely here", 0.1))[1] == 0


def test_a_glyph_read_as_several_characters_is_looked_at_one_by_one():
    assert tables.is_mark("✓") and tables.is_mark("x≤")
    assert not tables.is_mark("fi") and not tables.is_mark("")
