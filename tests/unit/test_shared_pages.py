from assembly import passes
from document.model import Chapter, Code, Heading, PageMarker, Paragraph, Table
from quality import book, chapter
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


def test_a_shared_page_is_scored_over_all_the_chapters_that_wrote_on_it():
    def checks(words):
        return {"shared_pages": {"5": {"layer": {"a": 1, "b": 1, "c": 1}, "got": words}}}

    assert book.shared_words([checks({"a": 1}), checks({"b": 1, "x": 1})]) == (1, 1, 3)


def test_neighbours_meeting_on_a_page_are_told_each_other_s_title():
    rows = [{"ord": n, "title": t, "level": 1, "first_page": a, "last_page": b, "kind": "chapter"}
            for n, t, a, b in ((1, "1. One", 1, 5), (2, "2. Two", 5, 9), (3, "3. Three", 10, 12))]
    got = assemble.chapters_of(rows)
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
    got = Chapter(ord=2, title="Two", level=1, first_page=5, last_page=6,
                  blocks=[_page(5), Paragraph(text=LAYER), _page(6), Paragraph(text=LAYER)])
    checks = chapter.check(got, [], {5: f"Two {LAYER}", 6: LAYER}, shared=frozenset({5}))
    assert checks["extra_words"] == 0
    assert checks["shared_pages"]["5"]["got"]["two"] == 1
