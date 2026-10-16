from assembly import passes
from document.model import Code, Heading, PageMarker, Paragraph, Piece, Table
from quality import book, piece
from stages import assemble

LAYER = "The quick brown fox jumps over the lazy dog while the cat sleeps by the warm fire tonight and every night"


def _page(n):
    return PageMarker(book_page=n, file_ord=0, file_page=n)


def test_a_chapter_starting_on_a_shared_page_keeps_only_what_follows_its_title():
    blocks = [_page(5), Paragraph(text="end of the last chapter"), Code(text="tail()"),
              Heading(text="2. Second", level=1, level_source="mineru"), Paragraph(text="its first words"),
              _page(6), Paragraph(text="more")]
    got, counts = passes.shared_pages(blocks, "2. Second", True, None)
    assert [getattr(b, "text", None) for b in got] == [None, "2. Second", "its first words", None, "more"]
    assert (counts["shared_cut_blocks"], counts["shared_title_missing"]) == (2, 0)


def test_a_chapter_ending_on_a_shared_page_gives_the_next_one_its_title_on_and_tables_with_it():
    blocks = [_page(7), Paragraph(text="ours"), Heading(text="3. Third", level=1, level_source="docling"),
              Table(rows=[]), Paragraph(text="theirs")]
    got, counts = passes.shared_pages(blocks, "2. Second", False, "3. Third")
    assert [getattr(b, "text", None) for b in got] == [None, "ours"]
    assert counts["shared_cut_blocks"] == 3


def test_a_title_not_found_keeps_the_page_whole_and_is_counted():
    blocks = [_page(5), Paragraph(text="no title here")]
    got, counts = passes.shared_pages(blocks, "2. Second", True, None)
    assert (got, counts["shared_title_missing"]) == (blocks, 1)


def test_a_page_read_again_only_to_cut_at_goes_whole_to_the_next_piece_when_its_title_is_not_on_it():
    blocks = [_page(4), Paragraph(text="ours"), _page(5), Paragraph(text="theirs, title unread")]
    got, counts = passes.shared_pages(blocks, "2. Second", False, "3. Third", reread_page=5)
    assert [getattr(b, "text", None) for b in got] == [None, "ours", None]
    assert counts["shared_title_missing"] == 1


def test_a_re_read_page_the_engine_gave_nothing_for_leaves_the_piece_s_own_last_page_whole():
    blocks = [_page(4), Paragraph(text="ours")]
    got, counts = passes.shared_pages(blocks, "2. Second", False, "3. Third", reread_page=5)
    assert (got, counts["shared_title_missing"], counts["shared_cut_blocks"]) == (blocks, 1, 0)


def test_a_shared_page_is_scored_over_all_the_chapters_that_wrote_on_it():
    def checks(words):
        return {"shared_pages": {"5": {"layer": {"a": 1, "b": 1, "c": 1}, "got": words}}}

    assert book.shared_words([checks({"a": 1}), checks({"b": 1, "x": 1})]) == (1, 1, 3)


def test_neighbours_meeting_on_a_page_are_told_each_other_s_title():
    rows = [{"ord": n, "title": t, "level": 1, "first_page": a, "last_page": b, "kind": "node", "parent_ord": None}
            for n, t, a, b in ((1, "1. One", 1, 5), (2, "2. Two", 5, 9), (3, "3. Three", 10, 12))]
    got = assemble.pieces_of(rows, frozenset(), 0, reread=False)
    assert [(c["shared_start"], c["next_title"]) for c in got] == [(False, "2. Two"), (True, None), (False, None)]


def test_a_one_page_chapter_keeps_its_text_when_its_neighbour_s_title_reads_alike():
    blocks = [_page(3), Heading(text="Раздел I", level=1, level_source="mineru"), Paragraph(text="первый"),
              Heading(text="Раздел II", level=1, level_source="mineru"), Paragraph(text="второй")]
    got, counts = passes.shared_pages(blocks, "Раздел I", False, "Раздел II")
    assert [getattr(b, "text", None) for b in got] == [None, "Раздел I", "первый"]
    got, _ = passes.shared_pages(blocks, "Раздел II", True, None)
    assert [getattr(b, "text", None) for b in got] == [None, "Раздел II", "второй"]


def test_a_glyph_read_as_several_characters_is_looked_at_one_by_one():
    assert passes.is_mark("✓") and passes.is_mark("x≤")
    assert not passes.is_mark("fi") and not passes.is_mark("")


def test_a_title_on_a_shared_first_page_is_counted_once():
    got = Piece(ord=2, title="Two", level=1, first_page=5, last_page=6,
                  blocks=[_page(5), Paragraph(text=LAYER), _page(6), Paragraph(text=LAYER)])
    checks = piece.check(got, [], {5: f"Two {LAYER}", 6: LAYER}, shared=frozenset({5}))
    assert checks["extra_words"] == 0
    assert checks["shared_pages"]["5"]["got"]["two"] == 1


def test_a_boundary_page_gives_away_only_what_is_read_before_the_title_and_set_above_it():
    from document.model import Where

    def at(block, top):
        return block.model_copy(update={"where": Where(page=5, box=(0.1, top, 0.9, top + 0.05), engine="docling")})

    page = [_page(5), at(Paragraph(text="the last line of One."), 0.05), at(Paragraph(text="its first words"), 0.3),
            at(Paragraph(text="more of it"), 0.5), at(Heading(text="2. Second", level=1, level_source="docling"), 0.2),
            at(Paragraph(text="joined across the page"), 0.1)]
    got, _ = passes.shared_pages(page, "2. Second", True, None)
    assert [getattr(b, "text", None) for b in got] == [None, "its first words", "more of it", "2. Second",
                                                       "joined across the page"]
    got, _ = passes.shared_pages([_page(4), Paragraph(text="ours"), *page], "1. First", False, "2. Second",
                                 reread_page=5)
    assert [getattr(b, "text", None) for b in got] == [None, "ours", None, "the last line of One."]


def test_both_sides_of_a_boundary_cut_one_reading_into_halves_that_make_the_whole_page():
    from document.model import Where

    def at(block, top):
        return block.model_copy(update={"where": Where(page=5, box=(0.1, top, 0.9, top + 0.05), engine="mineru")})

    page = [_page(5), at(Paragraph(text="the last line of One."), 0.05), at(Paragraph(text="its first words"), 0.3),
            at(Heading(text="2. Second", level=1, level_source="mineru"), 0.2)]
    tail, record, line = passes.boundary_cut([_page(4), Paragraph(text="ours"), *page],
                                             passes.Boundary(5, "2. Second", True))
    head, _, _ = passes.boundary_cut(page, passes.Boundary(5, "2. Second", False))
    assert [getattr(b, "text", None) for b in tail] == [None, "ours", None, "the last line of One."]
    assert [getattr(b, "text", None) for b in head] == [None, "its first words", "2. Second"]
    assert (record["title_found"], record["tail_blocks"], line) == (True, ["the last line of One."], 0.2)
    other = [_page(5), at(Code(text="x = 1"), 0.1), at(Table(rows=[]), 0.6), Code(text="no box")]
    assert [type(b).__name__ for b in passes._sided(other, passes.Boundary(5, "2. Second", True), line)] == [
        "PageMarker", "Code"]
    assert [type(b).__name__ for b in passes._sided(other, passes.Boundary(5, "2. Second", False), line)] == [
        "PageMarker", "Table"]
    unread, _, _ = passes.boundary_cut([_page(4), Paragraph(text="ours"), _page(5), Paragraph(text="no title")],
                                       passes.Boundary(5, "2. Second", True))
    assert [getattr(b, "text", None) for b in unread] == [None, "ours"]


def test_a_label_set_over_the_next_title_stays_with_it_and_the_cut_runs_over_it():
    from document.model import Where

    def at(block, top):
        return block.model_copy(update={"where": Where(page=5, box=(0.1, top, 0.9, top + 0.05), engine="mineru")})

    page = [_page(5), at(Paragraph(text="Той поклати глава."), 0.05), at(Heading(text="Chapter 2", level=2,
            level_source="mineru"), 0.15), at(Heading(text="2. Second", level=1, level_source="mineru"), 0.25),
            at(Paragraph(text="its first words"), 0.35)]
    tail, record, line = passes.boundary_cut([_page(4), *page], passes.Boundary(5, "2. Second", True))
    head, _, _ = passes.boundary_cut(page, passes.Boundary(5, "2. Second", False))
    assert [getattr(b, "text", None) for b in tail] == [None, None, "Той поклати глава."]
    assert [getattr(b, "text", None) for b in head] == [None, "Chapter 2", "2. Second", "its first words"]
    assert (record["tail_blocks"], line) == (["Той поклати глава."], 0.15)
    alone, record, _ = passes.boundary_cut([_page(4), *page[:2], *page[3:]], passes.Boundary(5, "2. Second", True))
    assert record["tail_blocks"] == ["Той поклати глава."]
