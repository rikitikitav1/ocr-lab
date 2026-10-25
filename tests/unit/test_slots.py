from document.model import Heading, ListBlock, ListItem, PageMarker, Paragraph
from elements import code, running_heads


def _page(n):
    return PageMarker(book_page=n, file_ord=0, file_page=n)


def test_a_block_whose_whole_text_is_a_claimed_line_is_marked_and_a_body_line_with_it_is_not():
    slots = {1: [("Chapter 3. Streams", "repeat"), ("41", "folio")]}
    blocks = [_page(1), Paragraph(text="Chapter 3.  Streams"), Paragraph(text="41"),
              Paragraph(text="Streams carry data in Chapter 3. Streams"), _page(2), Paragraph(text="41")]
    got, n = running_heads.mark_slots(blocks, slots)
    assert n == 2 and [getattr(b, "slot", None) for b in got] == [None, "repeat", "folio", None, None, None]


def test_an_engine_that_glued_head_and_folio_is_marked_and_a_list_item_goes_alone():
    slots = {1: [("Notes for Professionals", "repeat"), ("12", "folio")]}
    blocks = [_page(1), Paragraph(text="Notes for Professionals 12"),
              ListBlock(ordered=False, items=[ListItem(text="12"), ListItem(text="a real item")])]
    got, n = running_heads.mark_slots(blocks, slots)
    assert n == 2
    kept, dropped = running_heads.drop_slots(got)
    assert dropped == 2 and [i.text for i in kept[1].items] == ["a real item"] and len(kept) == 2


def test_a_heading_a_node_opens_at_stays_though_it_is_the_running_head():
    blocks = [_page(1), Heading(text="Обозначения", level=1, level_source="structure", node=4, slot="repeat"),
              Heading(text="Обозначения", level=2, level_source="mineru", slot="repeat"), Paragraph(text="body")]
    kept, dropped = running_heads.drop_slots(blocks)
    assert dropped == 1 and [type(b).__name__ for b in kept] == ["PageMarker", "Heading", "Paragraph"]


def _at(text, top):
    from document.model import Where
    return Paragraph(text=text, where=Where(page=1, box=(0.1, top, 0.9, top + 0.02), engine="mineru"))


def test_blocks_an_engine_cut_out_of_one_claimed_line_are_marked_together_when_they_stand_in_its_band():
    slots = {1: [("GoalKicker.com - Bash Notes for Professionals 12", "repeat", 0.95)]}
    blocks = [_page(1), _at("Body text that mentions Bash Notes", 0.5),
              _at("GoalKicker.com - Bash Notes for Professionals", 0.95), _at("12", 0.951)]
    got, n = running_heads.mark_slots(blocks, slots, parts=True)
    assert n == 2 and [getattr(b, "slot", None) for b in got] == [None, None, "repeat", "repeat"]
    assert running_heads.mark_slots(blocks, slots)[1] == 0


def test_a_part_alone_or_out_of_the_band_is_not_marked():
    slots = {1: [("Введение 7", "folio", 0.05)]}
    alone = [_page(1), _at("Введение", 0.05)]
    far = [_page(1), _at("Введение", 0.05), _at("7", 0.6)]
    assert running_heads.mark_slots(alone, slots, parts=True)[1] == 0
    assert running_heads.mark_slots(far, slots, parts=True)[1] == 0


def test_a_returned_note_does_not_keep_a_listing_from_joining_across_the_page():
    from document.model import Code, Where

    def block(text, page, top, bottom):
        return Code(text=text, where=Where(page=page, box=(0.1, top, 0.9, bottom), engine="mineru"))

    blocks = [_page(1), block("kind: ConfigWatcher", 1, 0.5, 0.95), Paragraph(text="1 See the operator docs."),
              _page(2), block("apiVersion: v1", 2, 0.05, 0.3)]
    got, n = code.join_code_across_pages(blocks)
    assert n == 1 and got[1].text == "kind: ConfigWatcher\napiVersion: v1" and got[2].text == "1 See the operator docs."
