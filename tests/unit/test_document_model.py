import pytest
from document.model import Document, Heading, ListBlock, ListItem, Piece
from pydantic import ValidationError


def test_a_heading_level_outside_the_range_is_refused():
    with pytest.raises(ValidationError):
        Heading(text="Too deep", level=6, level_source="engine")
    with pytest.raises(ValidationError):
        Heading(text="Above its chapter", level=0, level_source="engine")


def test_blocks_round_trip_through_json_by_their_type():
    piece = Piece(ord=1, title="One", level=1, first_page=3, last_page=9, blocks=[
        {"type": "heading", "text": "Inside", "level": 1, "level_source": "structure"},
        {"type": "code", "text": "print(1)", "language": "python"},
        {"type": "list", "ordered": False, "items": [{"text": "a", "children": [
            {"type": "list", "ordered": True, "items": [{"text": "b"}]}]}]},
    ])
    again = Document.model_validate_json(Document(title="Book", pieces=[piece]).model_dump_json())
    assert [type(b).__name__ for b in again.pieces[0].blocks] == ["Heading", "Code", "ListBlock"]
    assert isinstance(again.pieces[0].blocks[2].items[0].children[0], ListBlock)
    assert again.pieces[0].blocks[2].items[0].children[0].items == [ListItem(text="b")]
