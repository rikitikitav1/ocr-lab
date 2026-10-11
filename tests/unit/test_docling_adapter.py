from document.model import Caption, Figure, Footnote, Heading, ListBlock, PageMarker, Paragraph, Table
from engines import docling_adapter


def _text(i, label, text, page=1, parent="#/body", **extra):
    return {"self_ref": f"#/texts/{i}", "parent": {"$ref": parent}, "children": [], "content_layer": "body",
            "label": label, "prov": [{"page_no": page}], "orig": text, "text": text, **extra}


def _doc(texts, groups=(), tables=(), pictures=(), body=None):
    refs = body or [t["self_ref"] for t in texts if t["parent"]["$ref"] == "#/body"]
    return {"body": {"children": [{"$ref": r} for r in refs]}, "texts": list(texts), "groups": list(groups),
            "tables": list(tables), "pictures": list(pictures)}


def _read(doc):
    return docling_adapter.read(doc, 2, lambda page: page - 10)


def test_running_heads_are_counted_apart_and_pages_are_marked_once():
    doc = _doc([_text(0, "page_header", "Chapter One", 11), _text(1, "section_header", "Start", 11, level=1),
                _text(2, "text", "Body.", 11), _text(3, "page_footer", "12", 12), _text(4, "text", "More.", 12)])
    doc["texts"][0]["content_layer"] = doc["texts"][3]["content_layer"] = "furniture"
    got = _read(doc)
    assert got.furniture == ["Chapter One", "12"]
    assert got.blocks == [PageMarker(book_page=1, file_ord=2, file_page=11),
                          Heading(text="Start", level=1, level_source="docling"), Paragraph(text="Body."),
                          PageMarker(book_page=2, file_ord=2, file_page=12), Paragraph(text="More.")]


def test_a_list_keeps_its_start_and_a_nested_list():
    group = {"self_ref": "#/groups/0", "label": "ordered_list", "children": [{"$ref": "#/texts/0"},
                                                                            {"$ref": "#/texts/1"}]}
    inner = {"self_ref": "#/groups/1", "label": "list", "children": [{"$ref": "#/texts/2"}]}
    texts = [_text(0, "list_item", "first", parent="#/groups/0", marker="3.", enumerated=True),
             _text(1, "list_item", "second", parent="#/groups/0", marker="4.", enumerated=True),
             _text(2, "list_item", "inside", parent="#/groups/1", marker="-")]
    texts[1]["children"] = [{"$ref": "#/groups/1"}]
    got = [b for b in _read(_doc(texts, [group, inner], body=["#/groups/0"])).blocks if isinstance(b, ListBlock)]
    assert len(got) == 1 and got[0].ordered and got[0].start == 3
    assert [i.text for i in got[0].items] == ["first", "second"]
    assert got[0].items[1].children[0].items[0].text == "inside"


def test_a_table_keeps_spans_headers_and_its_caption():
    def cell(r, c, text, rs=1, cs=1, head=False):
        return {"start_row_offset_idx": r, "start_col_offset_idx": c, "row_span": rs, "col_span": cs,
                "text": text, "column_header": head}

    table = {"self_ref": "#/tables/0", "label": "table", "prov": [{"page_no": 11}], "captions": [{"$ref": "#/texts/0"}],
             "footnotes": [], "data": {"table_cells": [cell(0, 1, "B", head=True), cell(0, 0, "A", rs=2, head=True),
                                                       cell(1, 1, "b1")]}}
    got = _read(_doc([_text(0, "caption", "Table 1. Letters", 11, parent="#/tables/0")], tables=[table],
                     body=["#/tables/0"])).blocks
    assert isinstance(got[1], Table) and [[c.text for c in row] for row in got[1].rows] == [["A", "B"], ["b1"]]
    assert got[1].rows[0][0].rowspan == 2 and got[1].rows[0][0].header and got[2] == Caption(text="Table 1. Letters")


def test_a_picture_goes_where_the_caller_keeps_it_and_a_footnote_keeps_its_mark():
    picture = {"self_ref": "#/pictures/0", "label": "picture", "prov": [{"page_no": 11}], "captions": []}
    doc = _doc([_text(0, "footnote", "2 \t A note on terms.", 11), _text(1, "footnote", "No mark here", 11)],
               pictures=[picture], body=["#/pictures/0", "#/texts/0", "#/texts/1"])
    got = docling_adapter.read(doc, 1, lambda page: page, keep_image=lambda p: "images/p11.png").blocks
    assert got[1:] == [Figure(image="images/p11.png"), Footnote(mark="2", text="A note on terms."),
                       Footnote(mark="note1", text="No mark here")]


def test_an_unknown_label_stays_as_prose_and_is_counted():
    got = _read(_doc([_text(0, "document_index", "Index of terms")]))
    assert got.blocks[1:] == [Paragraph(text="Index of terms")] and got.unknown == {"document_index": 1}


def test_a_block_keeps_its_place_as_shares_of_the_page_from_the_top_left():
    text = _text(0, "text", "Body.", 3)
    text["prov"][0]["bbox"] = {"l": 50, "t": 700, "r": 250, "b": 600, "coord_origin": "BOTTOMLEFT"}
    doc = _doc([text])
    doc["pages"] = {"3": {"size": {"width": 500, "height": 800}}}
    where = _read(doc).blocks[1].where
    assert (where.page, where.engine) == (3, "docling") and where.box == (0.1, 0.125, 0.5, 0.25)


def test_a_table_keeps_the_empty_cells_docling_leaves_out():
    def cell(r, c, text, rs=1, cs=1):
        return {"start_row_offset_idx": r, "end_row_offset_idx": r + rs, "start_col_offset_idx": c,
                "end_col_offset_idx": c + cs, "row_span": rs, "col_span": cs, "text": text}

    data = {"num_rows": 2, "num_cols": 3, "table_cells": [cell(0, 0, "Feature"), cell(0, 1, "A"), cell(0, 2, "B"),
                                                          cell(1, 0, "sync"), cell(1, 2, "•")]}
    assert [[c.text for c in row] for row in docling_adapter.grid(data)] == [["Feature", "A", "B"], ["sync", "", "•"]]
    spanned = {"num_rows": 2, "num_cols": 2, "table_cells": [cell(0, 0, "x", rs=2), cell(0, 1, "a"), cell(1, 1, "b")]}
    assert [[c.text for c in row] for row in docling_adapter.grid(spanned)] == [["x", "a"], ["b"]]
