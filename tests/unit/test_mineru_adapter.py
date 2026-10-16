from document.model import Caption, Code, Figure, Footnote, Formula, Heading, PageMarker, Paragraph, Table
from engines import mineru_adapter


def _b(i, kind, text="", **extra):
    content = text if isinstance(text, list) else [{"type": "text", "content": text}]
    return {"index": i, "type": kind, "content": content, **extra}


def _read(*pages):
    doc = {"pages": [{"page_idx": idx, "blocks": blocks} for idx, blocks in pages]}
    return mineru_adapter.read(doc, 1, lambda page: page - 2)


def test_running_heads_are_counted_apart_and_a_broken_paragraph_is_joined():
    got = _read((10, [_b(0, "header", "Chapter One"), _b(1, "paragraph_title", "Start", level=2),
                      _b(2, "text", "The paragraph runs"), _b(3, "page_number", "11")]),
                (11, [_b(0, "text", "on to the next page.", continues_prev=True), _b(1, "aside_text", "SERIES")]))
    assert got.furniture == ["Chapter One", "11", "SERIES"]
    assert got.blocks == [PageMarker(book_page=9, file_ord=1, file_page=11),
                          Heading(text="Start", level=2, level_source="mineru"),
                          Paragraph(text="The paragraph runs on to the next page."),
                          PageMarker(book_page=10, file_ord=1, file_page=12)]


def test_inline_formulas_stay_in_the_text_and_a_block_formula_is_its_own():
    got = _read((0, [_b(0, "text", [{"type": "text", "content": "Energy "},
                                    {"type": "equation_inline", "content": "E=mc^2"}]),
                     {"index": 1, "type": "equation", "content": "a^2+b^2=c^2"}]))
    assert got.blocks[1:] == [Paragraph(text="Energy $E=mc^2$"), Formula(latex="a^2+b^2=c^2")]


def test_a_table_keeps_spans_and_its_caption_and_a_figure_goes_where_the_caller_keeps_it():
    html = "<table><tr><th rowspan=\"2\">A</th><th>B</th></tr><tr><td>b1<br>b2</td></tr></table>"
    table = _b(0, "table", [{"type": "table_caption", "content": [{"type": "text", "content": "Table 1"}]},
                            {"type": "table_body", "content": html}])
    image = _b(1, "image", [{"type": "image_body", "content": "", "index": 7}])
    doc = {"pages": [{"page_idx": 4, "blocks": [table, image]}]}
    got = mineru_adapter.read(doc, 1, lambda p: p, keep_image=lambda part, page: f"img/{page}-{part['index']}.png")
    assert got.blocks[1] == Caption(text="Table 1") and got.blocks[3] == Figure(image="img/5-7.png")
    assert isinstance(got.blocks[2], Table)
    assert [[(c.text, c.header, c.rowspan) for c in row] for row in got.blocks[2].rows] == [
        [("A", True, 2), ("B", True, 1)], [("b1\nb2", False, 1)]]


def test_code_footnotes_and_an_unknown_type():
    code = _b(0, "code", [{"type": "code_body", "content": "x = 1\ny = 2"}], guess_lang="python")
    got = _read((0, [code, _b(1, "page_footnote", "3 A note."), _b(2, "seal", "Stamp")]))
    assert got.blocks[1:] == [Code(text="x = 1\ny = 2", language="python"), Footnote(mark="3", text="A note."),
                              Paragraph(text="Stamp")]
    assert got.unknown == {"seal": 1}


def test_a_block_keeps_mineru_s_own_box_and_the_page_counted_from_one():
    block = dict(_b(0, "text", "Body."), bbox=[0.1, 0.2, 0.5, 0.3])
    got = _read((4, [block]))
    where = got.blocks[1].where
    assert (where.page, where.box, where.engine) == (5, (0.1, 0.2, 0.5, 0.3), "mineru")


def test_a_range_out_of_memory_is_read_in_halves_and_its_parts_adapt_in_order(monkeypatch):
    from engines import converter_tools, reading

    asked = []

    def fake(path, given, first, last, ceiling, build=None):
        asked.append((first, last))
        if last - first >= 2:
            return {"status": "failure", "errors": ["CUDA out of memory. Tried to allocate"]}
        return {"status": "success", "structure": {"pages": [{"page_idx": p - 1, "blocks": [_b(0, "text", f"p{p}")]}
                                                             for p in range(first, last + 1)]}}

    monkeypatch.setattr(reading.card, "hand_to", lambda engine: None)
    monkeypatch.setitem(converter_tools.READ, "mineru", fake)
    got = reading.read("mineru", None, 1, 8, [], 1.0, splits=3)
    assert asked == [(1, 8), (1, 4), (1, 2), (3, 4), (5, 8), (5, 6), (7, 8)]
    assert len(got["parts"]) == 4
    texts = [b.text for b in reading.adapt("mineru", got).blocks if isinstance(b, Paragraph)]
    assert texts == [f"p{p}" for p in range(1, 9)]


def test_memory_still_short_at_the_last_split_names_it(monkeypatch):
    import pytest
    from engines import converter_tools, reading

    monkeypatch.setattr(reading.card, "hand_to", lambda engine: None)
    monkeypatch.setitem(converter_tools.READ, "mineru",
                        lambda *a, **k: {"status": "failure", "errors": ["CUDA out of memory"]})
    with pytest.raises(RuntimeError, match="out of memory even in halves"):
        reading.read("mineru", type("P", (), {"name": "b.pdf"})(), 1, 8, [], 1.0, splits=1)


def _halving(asked, kept):
    def fake(path, given, first, last, ceiling, build=None):
        asked.append((first, last))
        if last > first:
            return {"status": "failure", "errors": ["CUDA out of memory"]}
        return {"status": "success", **kept(first)}

    return fake


def _stand_in(monkeypatch, fake):
    import artifacts
    from engines import converter_tools, reading

    monkeypatch.setattr(reading.card, "hand_to", lambda engine: None)
    monkeypatch.setitem(converter_tools.READ, "mineru", fake)
    monkeypatch.setattr(reading, "build", lambda engine: {"base": "m"})
    monkeypatch.setattr(artifacts, "find_done", lambda *a: None)
    monkeypatch.setattr(artifacts, "book_dir", lambda book_id: None)
    monkeypatch.setattr(artifacts, "write", lambda *a, **k: None)


def test_the_contents_scan_reads_a_chunk_in_halves_and_places_every_page(monkeypatch):
    from types import SimpleNamespace

    from stages import intake
    from stages.structure import scan

    asked = []
    _stand_in(monkeypatch, _halving(asked, lambda p: {"structure": {"pages": [{"page_idx": p - 1, "blocks": []}]}}))
    monkeypatch.setattr(intake, "files_of", lambda book_id: [SimpleNamespace(
        ord=1, first_page=1, pages=10, sha256="f", file_path="b.pdf")])
    got = scan.recognise(1, [2, 3])
    assert asked == [(2, 3), (2, 2), (3, 3)]
    assert sorted(got) == [2, 3]


def test_title_pages_out_of_memory_are_read_in_halves_and_their_markdown_joined(monkeypatch):
    from types import SimpleNamespace

    from stages.metadata import resolve

    asked = []
    _stand_in(monkeypatch, _halving(asked, lambda p: {"markdown": f"page {p}"}))
    monkeypatch.setattr(resolve, "window", lambda book_id: (2, 1))
    f = SimpleNamespace(ord=1, pages=5, sha256="f", file_path="b.pdf")
    assert resolve._recognised_title_pages(1, f, f) == "page 1\npage 2\npage 5"
    assert asked == [(1, 2), (1, 1), (2, 2), (5, 5)]


def test_a_kept_reading_without_markdown_reads_as_empty_text(monkeypatch):
    from engines import converter_tools, reading

    monkeypatch.setattr(reading.card, "hand_to", lambda engine: None)
    monkeypatch.setitem(converter_tools.READ, "mineru", lambda *a, **k: {"status": "partial_success"})
    assert reading.read_markdown("mineru", None, 1, 1, [], 1.0) == ""
