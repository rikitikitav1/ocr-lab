from assembly import passes
from document.model import Heading, ListBlock, ListItem, PageMarker, Paragraph


def _page(n):
    return PageMarker(book_page=n, file_ord=0, file_page=n)


def test_a_block_whose_whole_text_is_a_claimed_line_is_marked_and_a_body_line_with_it_is_not():
    slots = {1: [("Chapter 3. Streams", "repeat"), ("41", "folio")]}
    blocks = [_page(1), Paragraph(text="Chapter 3.  Streams"), Paragraph(text="41"),
              Paragraph(text="Streams carry data in Chapter 3. Streams"), _page(2), Paragraph(text="41")]
    got, n = passes.mark_slots(blocks, slots)
    assert n == 2 and [getattr(b, "slot", None) for b in got] == [None, "repeat", "folio", None, None, None]


def test_an_engine_that_glued_head_and_folio_is_marked_and_a_list_item_goes_alone():
    slots = {1: [("Notes for Professionals", "repeat"), ("12", "folio")]}
    blocks = [_page(1), Paragraph(text="Notes for Professionals 12"),
              ListBlock(ordered=False, items=[ListItem(text="12"), ListItem(text="a real item")])]
    got, n = passes.mark_slots(blocks, slots)
    assert n == 2
    kept, dropped = passes.drop_slots(got)
    assert dropped == 2 and [i.text for i in kept[1].items] == ["a real item"] and len(kept) == 2


def test_a_heading_a_node_opens_at_stays_though_it_is_the_running_head():
    blocks = [_page(1), Heading(text="Обозначения", level=1, level_source="structure", node=4, slot="repeat"),
              Heading(text="Обозначения", level=2, level_source="mineru", slot="repeat"), Paragraph(text="body")]
    kept, dropped = passes.drop_slots(blocks)
    assert dropped == 1 and [type(b).__name__ for b in kept] == ["PageMarker", "Heading", "Paragraph"]


def _at(text, top):
    from document.model import Where
    return Paragraph(text=text, where=Where(page=1, box=(0.1, top, 0.9, top + 0.02), engine="mineru"))


def test_blocks_an_engine_cut_out_of_one_claimed_line_are_marked_together_when_they_stand_in_its_band():
    slots = {1: [("GoalKicker.com - Bash Notes for Professionals 12", "repeat", 0.95)]}
    blocks = [_page(1), _at("Body text that mentions Bash Notes", 0.5),
              _at("GoalKicker.com - Bash Notes for Professionals", 0.95), _at("12", 0.951)]
    got, n = passes.mark_slots(blocks, slots, parts=True)
    assert n == 2 and [getattr(b, "slot", None) for b in got] == [None, None, "repeat", "repeat"]
    assert passes.mark_slots(blocks, slots)[1] == 0


def test_a_part_alone_or_out_of_the_band_is_not_marked():
    slots = {1: [("Введение 7", "folio", 0.05)]}
    alone = [_page(1), _at("Введение", 0.05)]
    far = [_page(1), _at("Введение", 0.05), _at("7", 0.6)]
    assert passes.mark_slots(alone, slots, parts=True)[1] == 0
    assert passes.mark_slots(far, slots, parts=True)[1] == 0


def test_a_footnote_an_engine_set_aside_comes_back_at_its_page_s_end_where_the_layout_reads_a_note():
    from types import SimpleNamespace

    read = SimpleNamespace(furniture_at=[(1, "footer", "16 For discussion of these ideals see Duke, 2013."),
                                         (1, "page_number", "104"), (2, "footer", "16 For discussion of it")])
    blocks = [_page(1), Paragraph(text="body"), _page(2), Paragraph(text="more")]
    notes = {1: " 16 for discussion of these ideals see duke, 2013. 104 "}
    got, n = passes.notes_from_furniture(blocks, {"mineru": read}, {1: {"picked": "mineru"}, 2: {"picked": "mineru"}},
                                         notes)
    assert n == 1 and [getattr(b, "text", None) for b in got] == [
        None, "body", "16 For discussion of these ideals see Duke, 2013.", None, "more"]


def test_a_returned_note_does_not_keep_a_listing_from_joining_across_the_page():
    from document.model import Code, Where

    def code(text, page, top, bottom):
        return Code(text=text, where=Where(page=page, box=(0.1, top, 0.9, bottom), engine="mineru"))

    blocks = [_page(1), code("kind: ConfigWatcher", 1, 0.5, 0.95), Paragraph(text="1 See the operator docs."),
              _page(2), code("apiVersion: v1", 2, 0.05, 0.3)]
    got, n = passes.join_code_across_pages(blocks)
    assert n == 1 and got[1].text == "kind: ConfigWatcher\napiVersion: v1" and got[2].text == "1 See the operator docs."


def test_a_chapter_s_section_list_becomes_one_contents_block_and_a_chain_of_headings_does_not():
    from document.model import Contents, Heading, Paragraph

    nodes = [{"title": "1 Systems", "level": 1, "first_page": 1}, {"title": "1.1 Introduction", "level": 2},
             {"title": "1.2 Examples", "level": 2}, {"title": "1.3 Trends", "level": 2}]
    rows = "SYSTEMS\n1.1 Introduction\n1.2 Examples\n1.3 Trends\nA distributed system is one in which components"
    blocks = [_page(1), Paragraph(text="1.1 Introduction"), Paragraph(text="1.2 Examples"),
              Paragraph(text="1.3 Trends"), Paragraph(text="A distributed system is one in which components"), _page(2),
              Heading(text="1.1 Introduction", level=2, level_source="docling")]
    out, n = passes.chapter_contents(blocks, nodes, {1: rows})
    assert n == 1 and isinstance(out[1], Contents) and out[1].entries == ["1.1 Introduction", "1.2 Examples",
                                                                          "1.3 Trends"]
    assert isinstance(out[-1], Heading)
    chain = [{"title": "2 Law", "level": 1, "first_page": 1}, {"title": "A. Basis", "level": 2},
             {"title": "1. Pledge", "level": 3}, {"title": "a) Scope", "level": 4}]
    assert passes.chapter_contents(blocks, chain, {1: "A. Basis\n1. Pledge\na) Scope\nText"})[1] == 0


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
    out, n = passes.chapter_contents(blocks, nodes, {1: rows})
    assert n == 1 and isinstance(out[1], Contents)
    assert out[1].entries == ["1.1 Introduction", "1.1.1 Scope", "1.2 Examples", "1.3 Trends"]


def test_a_contents_row_drops_its_page_arabic_or_roman_after_a_leader_and_a_title_keeps_its_numeral():
    assert passes._entry("1.1 Introduction ..... xv") == passes._entry("1.1 Introduction 12") == "introduction"
    assert passes._entry("World War II") == "world war ii"
