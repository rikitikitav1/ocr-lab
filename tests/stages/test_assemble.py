from types import SimpleNamespace

from assembly import passes
from document.model import Code, Figure, Heading, PageMarker, Paragraph, Where
from stages import assemble, intake, piece_assembly, running_heads

from tests.fixtures import build, text_page
from tests.real_db import needs_db


def _file(ord, first_page, pages):
    return SimpleNamespace(ord=ord, first_page=first_page, pages=pages)


def test_a_chapter_splits_at_file_boundaries_into_in_file_pages():
    files = [_file(0, 1, 4), _file(1, 5, 6)]
    got = [(f.ord, a, b) for f, a, b in assemble.file_ranges(files, 3, 7)]
    assert got == [(0, 3, 4), (1, 1, 3)]


def test_cut_pages_split_a_chapter_s_ranges_and_leave_it_out_when_they_are_all_it_has():
    files = [_file(0, 1, 8)]
    got = [(a, b) for _, a, b in assemble.file_ranges(files, 1, 8, frozenset({2, 3, 4}))]
    assert got == [(1, 1), (5, 8)]

    def row(ord, kind, title, first, last):
        return {"ord": ord, "kind": kind, "title": title, "level": 1, "first_page": first, "last_page": last,
                "parent_ord": None}

    rows = [row(1, "front_matter", "Cover", 1, 1), row(2, "node", "Content list", 2, 4), row(3, "node", "One", 5, 8)]
    got = assemble.pieces_of(rows, frozenset({2, 3, 4}), 0, reread=False)
    assert [c["title"] for c in got] == ["Cover", "One"]


def test_pieces_go_down_the_tree_by_level_and_length_and_never_cut_a_node_by_pages():
    def node(ord, title, level, first, last, parent=None):
        return {"ord": ord, "kind": "node", "title": title, "level": level, "first_page": first, "last_page": last,
                "parent_ord": parent}

    rows = [node(0, "Part I", 0, 1, 260), node(1, "One", 1, 3, 40, 0), node(2, "1.1", 2, 10, 40, 1),
            node(3, "Two", 1, 41, 260, 0), node(4, "Index", 0, 261, 400)]
    got = assemble.pieces_of(rows, frozenset(), 0)
    pieces = [(c["title"], c["first_page"], c["last_page"], c["shared_start"], c["next_title"]) for c in got]
    assert pieces == [("Part I", 1, 3, False, "One"), ("One", 3, 41, True, "Two"), ("Two", 41, 261, True, "Index"),
                      ("Index", 261, 400, True, None)]
    assert [c.get("reread_start", False) for c in got] == [False, True, True, True]
    assert [c.get("reread_start", False) for c in assemble.pieces_of(rows, frozenset(), 0, reread=False)] == [
        False, False, False, False]
    # the re-read page is the next piece's, less the tail the earlier piece took; that piece measures its tail alone
    layer = {3: "the end of part i one begins here", 41: "two begins"}
    cuts = [{"page": 3, "read": True, "tail_text": "The end of Part I"}, {"page": 41, "read": True, "tail_text": ""}]
    assert piece_assembly.measured_layer(got[0], layer, cuts)[3] == "The end of Part I"
    assert piece_assembly.measured_layer(got[1], layer, cuts) == {3: "one begins here", 41: ""}
    assert piece_assembly.measured_layer(got[2], layer, cuts)[41] == "two begins"
    assert piece_assembly.measured_layer(got[1], layer, []) == {3: "the end of part i one begins here", 41: ""}
    assert [n["title"] for n in assemble.pieces_of(rows, frozenset(), 0)[1]["nodes"]] == ["One", "1.1"]
    by_one = [c["title"] for c in assemble.pieces_of(rows, frozenset(), 2)]
    assert by_one == ["Part I", "One", "1.1", "Two", "Index"]


def test_a_one_page_piece_the_next_opens_on_holds_the_next_one():
    rows = [{"ord": o, "kind": "node", "title": t, "level": 0, "first_page": a, "last_page": b, "parent_ord": None}
            for o, t, a, b in ((1, "One", 1, 77), (2, "Chapter 2: Consumption", 78, 78), (3, "Tax", 78, 90))]
    got = [(c["title"], c["first_page"], c["last_page"], [n["ord"] for n in c["nodes"]])
           for c in assemble.pieces_of(rows, frozenset(), 0)]
    assert got == [("One", 1, 78, [1]), ("Chapter 2: Consumption", 78, 90, [2, 3])]


def test_a_parent_opening_on_its_first_child_s_page_heads_that_child_s_piece():
    rows = [{"ord": 0, "kind": "part", "title": "Part I", "level": 0, "first_page": 1, "last_page": 300,
             "parent_ord": None},
            {"ord": 1, "kind": "node", "title": "One", "level": 1, "first_page": 1, "last_page": 150,
             "parent_ord": 0},
            {"ord": 2, "kind": "node", "title": "Two", "level": 1, "first_page": 151, "last_page": 300,
             "parent_ord": 0}]
    got = assemble.pieces_of(rows, frozenset(), 0)
    assert [(c["title"], [n["title"] for n in c["nodes"]], c["subs"]) for c in got] == [
        ("Part I", ["Part I", "One"], [("One", 1)]), ("Two", ["Two"], [])]


def test_in_a_piece_a_label_opens_its_node_and_an_unpinned_node_opens_at_its_title_or_its_page():
    def mark(page):
        return PageMarker(book_page=page, file_ord=0, file_page=page)

    blocks = [mark(1), Paragraph(text="end of the part"), Heading(text="ГЛАВА 2", level=5, level_source="engine"),
              Heading(text="Types", level=1, level_source="structure"), mark(2), Paragraph(text="Methods"),
              Paragraph(text="body"), mark(3), Paragraph(text="more")]
    nodes = [{"ord": 2, "title": "Types", "level": 1, "first_page": 1, "last_page": 1, "parent_ord": 0},
             {"ord": 3, "title": "Methods", "level": 1, "first_page": 2, "last_page": 2, "parent_ord": 0},
             {"ord": 4, "title": "Results", "level": 1, "first_page": 3, "last_page": 3, "parent_ord": 0}]
    out, found = assemble._opened(blocks, [3, None, None], nodes, 0, piece=True)
    heads = [(b.text, b.level, b.node) for b in out if isinstance(b, Heading)]
    assert heads == [("ГЛАВА 2", 1, 2), ("Types", 1, None), ("Methods", 1, 3), ("Results", 1, 4)]
    assert [(n.pinned, n.anchored) for n in found] == [(True, True), (False, True), (False, True)]


def test_a_node_on_a_shared_page_opens_at_its_title_printed_with_a_label_word():
    blocks = [PageMarker(book_page=155, file_ord=0, file_page=155), Heading(text="Solution", level=2, level_source="x"),
              Paragraph(text="the end of the previous chapter's last section, in a long enough paragraph"),
              Heading(text="CHAPTER 16 Adapter", level=1, level_source="engine"), Paragraph(text="body")]
    nodes = [{"ord": 130, "title": "Solution", "level": 3, "first_page": 155, "last_page": 155, "parent_ord": 127},
             {"ord": 131, "title": "16. Adapter", "level": 2, "first_page": 155, "last_page": 158, "parent_ord": 120}]
    out, found = assemble._opened(blocks, [1, None], nodes, 1, piece=True, own_first=154)
    assert [n.anchored for n in found] == [True, True]
    assert [(b.text, b.node) for b in out if isinstance(b, Heading)] == [("Solution", 130), ("CHAPTER 16 Adapter", 131)]


def test_a_title_the_engine_glued_its_label_onto_is_found_on_letters_alone():
    blocks = [PageMarker(book_page=40, file_ord=0, file_page=40), Paragraph(text="the end of section B, long enough"),
              Heading(text="Scope of the studyC.", level=2, level_source="engine"), Paragraph(text="body")]
    nodes = [{"ord": 7, "title": "C. Scope of the study", "level": 2, "first_page": 40, "last_page": 44,
              "parent_ord": 2}]
    out, found = assemble._opened(blocks, [None], nodes, 1, piece=True, own_first=30)
    assert found[0].anchored and [b.text for b in out if isinstance(b, Heading) and b.node] == ["Scope of the studyC."]
    assert passes.titled_loosely(blocks, 1, 4, "Redis") is None
    xref = [PageMarker(book_page=9, file_ord=0, file_page=9), Paragraph(text="See the X-Case, p. 323")]
    assert passes.titled_loosely(xref, 1, 2, "The X-Case") is None


def test_a_code_line_reading_as_a_node_s_title_stays_code():
    blocks = [PageMarker(book_page=12, file_ord=0, file_page=12), Paragraph(text="text before, long enough here"),
              Code(text="print_report"), Paragraph(text="more")]
    nodes = [{"ord": 76, "title": "print_report", "level": 2, "first_page": 12, "last_page": 13, "parent_ord": 70}]
    out, _ = assemble._opened(blocks, [None], nodes, 1, piece=True, own_first=10)
    assert any(isinstance(b, Code) and b.text == "print_report" for b in out)


def test_nodes_placed_on_one_page_keep_their_order_and_a_second_without_a_title_is_not_guessed():
    blocks = [PageMarker(book_page=4, file_ord=0, file_page=4), Paragraph(text="text"), Paragraph(text="Gamma"),
              Paragraph(text="more")]
    nodes = [{"ord": o, "title": t, "level": 1, "first_page": 4, "last_page": 4, "parent_ord": 0}
             for o, t in ((1, "Alpha"), (2, "Beta"), (3, "Gamma"))]
    out, found = assemble._opened(blocks, [None, None, None], nodes, 0, piece=True)
    # the first goes to the page's top; a second opening on that page has no known place and stays in the first
    assert [b.text for b in out if isinstance(b, Heading)] == ["Alpha", "Gamma"]
    assert [n.anchored for n in found] == [True, False, True]


def test_every_block_belongs_to_the_node_last_opened_before_it_and_a_page_set_node_is_marked():
    def mark(page):
        return PageMarker(book_page=page, file_ord=0, file_page=page)

    blocks = [mark(1), Paragraph(text="own"), Heading(text="A", level=1, level_source="structure", node=5), mark(2),
              Paragraph(text="in A"), Heading(text="B", level=1, level_source="page", node=6), Paragraph(text="in B")]
    got = [(b.text, b.parent_ord, b.by_page) for b in assemble._owned(blocks, 4, False) if hasattr(b, "text")]
    assert got == [("own", 4, False), ("A", 5, False), ("in A", 5, False), ("B", 6, True), ("in B", 6, True)]
    first = [(b.text, b.by_page) for b in assemble._owned(blocks[:2] + [mark(2), Paragraph(text="later")], 4, True)
             if hasattr(b, "text")]
    assert first == [("own", True), ("later", False)]


def test_a_figure_with_a_box_gets_its_picture_cut_from_the_page_and_named_for_the_bundle(monkeypatch):
    monkeypatch.setattr(assemble.pdf, "page_crop", lambda path, index, box: f"png {index} {box}".encode())
    kept: dict = {}

    def keep(png):
        kept[f"images/07-{len(kept) + 1:03d}.png"] = png
        return f"images/07-{len(kept):03d}.png"

    placed = Figure(image="picture 1", where=Where(page=3, box=(0.1, 0.2, 0.5, 0.6), engine="mineru"))
    got = assemble._kept_figures("book.pdf", [placed, Figure(image="no box")], keep)
    assert [f.image for f in got] == ["images/07-001.png", "no box"]
    assert kept == {"images/07-001.png": b"png 2 (0.1, 0.2, 0.5, 0.6)"}


def test_the_first_page_before_the_first_toc_row_is_cut_as_a_cover_but_a_paper_s_first_page_stays():
    def row(kind, first):
        return {"kind": kind, "first_page": first}

    assert assemble._cover([row("front_matter", 1), row("node", 2)]) == {1}
    assert assemble._cover([row("node", 1), row("node", 5)]) == frozenset()


def _roles(rows: list[dict]) -> list[str]:
    return assemble.roles(rows, max(r["last_page"] for r in rows))


def test_unnumbered_chapters_on_both_edges_of_the_numbered_run_are_service():
    def row(title, first):
        return {"kind": "node", "title": title, "level": 1, "first_page": first, "last_page": first}

    book = [row("Preface", 1), row("Благодарности", 2), {**row("1 Basics", 3), "last_page": 95}, row("Afterword", 96)]
    book[-1]["last_page"] = 100
    roles = _roles(book)
    assert roles == ["service", "service", "body", "service"]
    assert set(_roles([row("Preface", 1), row("Basics", 2)])) == {"body"}
    roman = [row("Foreword", 1), row("Глава IV", 2)]
    roman[-1]["last_page"] = 100
    assert _roles(roman)[0] == "service"
    words = [row("What I Learned", 1), row("C Programming", 2), row("1 Basics", 3)]
    words[-1]["last_page"] = 100
    assert _roles(words) == ["service", "service", "body"]
    parts = [row("Preface", 1), row("Часть I Основы", 3), row("Глава", 4), row("Часть II Дальше", 6)]
    parts[-1]["last_page"] = 100
    assert _roles(parts) == ["service", "body", "body", "body"]
    late = [row("Preface", 1), row("Processes", 2)] + [row(f"Topic {n}", 40 + n) for n in range(1, 3)]
    late[-1]["last_page"] = 100
    assert set(_roles(late)) == {"body"}
    early = [row("1 Basics", 1), row("2 More", 10), row("Appendix", 20)]
    early[-1]["last_page"] = 100
    assert _roles(early) == ["body", "body", "body"]


def test_a_chapter_s_ranges_split_where_pages_turn_from_layer_to_recognition(monkeypatch):
    monkeypatch.setattr(assemble.intake, "files_of", lambda book_id: [_file(0, 1, 6), _file(1, 7, 4)])
    monkeypatch.setattr(assemble, "scanned_pages", lambda book_id: frozenset({3, 4, 7}))
    got = [(f.ord, a, b, regime) for f, a, b, regime in assemble.ranges(1, 2, 9)]
    assert got == [(0, 2, 2, "text_pdf"), (0, 3, 4, "scan"), (0, 5, 6, "text_pdf"), (1, 1, 1, "scan"),
                   (1, 2, 3, "text_pdf")]


def test_recognised_pages_take_one_engine_s_text_and_measure_the_two_engines_agreement():
    def read(*pages):
        blocks = []
        for n, text in pages:
            blocks += [PageMarker(book_page=n, file_ord=0, file_page=n), Paragraph(text=text)]
        return SimpleNamespace(blocks=blocks)

    reads = {"docling": read((1, "the quick brown fox"), (2, "noise")), "mineru": read((1, "the quick brown fox"),
                                                                                       (2, "a page of text"))}
    blocks, found, agreement = passes.recognised(reads, "mineru")
    assert blocks is reads["mineru"].blocks and found == {"pages_recognised": 2, "pages_picture": 0}
    assert agreement == {1: 1.0, 2: 0.0}


def test_a_recognised_page_with_too_few_words_is_a_picture_with_no_agreement():
    def read(*pages):
        blocks = []
        for n, text in pages:
            blocks += [PageMarker(book_page=n, file_ord=0, file_page=n), Paragraph(text=text)]
        return SimpleNamespace(blocks=blocks)

    reads = {"docling": read((1, "the quick brown fox")), "mineru": read((1, "the quick brown fox"), (2, "Plate IV"))}
    _, found, agreement = passes.recognised(reads, "mineru", min_words=3)
    assert found == {"pages_recognised": 1, "pages_picture": 1} and agreement == {1: 1.0}
    reads["docling"] = read((1, "the quick brown fox"), (2, "a page the other engine read"))
    _, found, agreement = passes.recognised(reads, "mineru", min_words=3)
    assert found == {"pages_recognised": 2, "pages_picture": 0} and agreement[2] == 0.0


def test_a_heading_deeper_than_the_writer_allows_is_demoted_and_counted_never_raised():
    blocks = [Heading(text="Intro", level=2, level_source="docling"), Heading(text="1.1 Basics", level=3,
              level_source="docling"), Heading(text="deep", level=5, level_source="docling")]
    out, counts = passes.piece_levels(blocks, 2, [("1.1 Basics", 3)])
    assert [(h.level, h.level_source) for h in out] == [(1, "docling"), (1, "structure"), (3, "docling")]
    assert counts == {"headings_from_structure": 1, "headings_demoted": 1, "headings_flattened": 0}


def _docling(page_no, heading, text):
    def item(i, label, value, **extra):
        return {"self_ref": f"#/texts/{i}", "parent": {"$ref": "#/body"}, "children": [], "content_layer": "body",
                "label": label, "prov": [{"page_no": page_no, "bbox": {"l": 50, "t": 750 - 60 * i, "r": 500,
                                                                        "b": 720 - 60 * i}}],
                "orig": value, "text": value, **extra}

    texts = [item(0, "section_header", heading, level=5), item(1, "text", text)]
    return {"body": {"children": [{"$ref": t["self_ref"]} for t in texts]}, "texts": texts, "groups": [],
            "tables": [], "pictures": [], "pages": {str(page_no): {"size": {"width": 595, "height": 842}}}}


def _mineru(page_idx, text):
    return {"pages": [{"page_idx": page_idx, "blocks": [
        {"index": 0, "type": "text", "bbox": [0.1, 0.2, 0.9, 0.3], "content": [{"type": "text", "content": text}]}]}]}


@needs_db
def test_a_chapter_over_two_files_is_assembled_without_engines(stand, tmp_path, monkeypatch):
    a = build(tmp_path / "a.pdf", [text_page("Front"), text_page("Deep heading", "First file body text.")])
    b = build(tmp_path / "b.pdf", [text_page("Second file body text.")])
    book, _ = intake.register([(a, "a.pdf"), (b, "b.pdf")])

    def canned(book_id, f, first, last, engine, languages, regime="text_pdf"):
        if engine == "docling":
            return _docling(first, "Deep heading", "First file body text." if f.ord == 0 else "Second file body text.")
        return _mineru(first - 1, "First file body text." if f.ord == 0 else "Second file body text.")

    monkeypatch.setattr(assemble, "_structure", canned)
    got = assemble.assemble(book, 1, "Chapter", 2, 2, 3, languages=["en"])
    markers = [(b.file_ord, b.file_page, b.book_page) for b in got.piece.blocks if isinstance(b, PageMarker)]
    assert markers == [(0, 2, 2), (1, 1, 3)]
    assert any(isinstance(b, Paragraph) and "Second file" in b.text for b in got.piece.blocks)
    assert "<!-- node ord=1 level=2 pages=2-3 role=body -->\n\n### Chapter\n\n#### Deep heading" in got.markdown
    assert [name for name, _ in got.steps[0]["steps"]][0] == "referee" and "furniture_docling" in got.counts
    # after the range passes come the piece passes, the last snapshot being the piece as written
    piece = got.steps[-1]
    assert (piece["file"], [name for name, _ in piece["steps"]]) == (
        "piece", ["shared_pages", "without_title", "chapter_contents", "piece_levels", "opened", "series_captions",
                  "slots_dropped", "owned"])
    assert piece["steps"][-1][1] == got.piece.blocks
    assert set(got.pages) == {2, 3} and all(set(p["scores"]) == {"docling", "mineru"} for p in got.pages.values())
    assert got.counts.get("pages_docling", 0) + got.counts.get("pages_mineru", 0) == 2


def test_the_chapter_title_set_again_on_its_first_page_goes():
    blocks = [PageMarker(book_page=1, file_ord=0, file_page=1), Heading(text="Chapter 7: COALESCE", level=1,
              level_source="docling"), Paragraph(text="Coalesce returns the first non null argument.")]
    out, dropped = passes.without_title(blocks, "Chapter 7: COALESCE")
    assert dropped == 1 and [type(b).__name__ for b in out] == ["PageMarker", "Paragraph"]
    assert passes.without_title(blocks, "Chapter 8: INSERT")[1] == 0
    labelled = [PageMarker(book_page=3, file_ord=0, file_page=3), Paragraph(text="Chapter 1"),
                Heading(text="Values, Types, and Operators", level=2, level_source="mineru"), Paragraph(text="Text.")]
    out, dropped = passes.without_title(labelled, "1 Values, Types, and Operators")
    assert dropped == 1 and [getattr(b, "text", None) for b in out] == [None, "Chapter 1", "Text."]


def test_lettered_appendices_count_as_numbered_and_a_lone_article_does_not():
    def row(title, first, last):
        return {"kind": "node", "title": title, "level": 1, "first_page": first, "last_page": last}

    book = [row("1 Basics", 1, 80), row("Appendix A: Keywords", 81, 90), row("Credits", 91, 92), row("Index", 93, 100)]
    assert _roles(book) == ["body", "body", "service", "service"]
    bare = [row("1 Basics", 1, 80), row("A Debugging", 81, 85), row("B Analysis", 86, 95), row("Index", 96, 100)]
    assert _roles(bare) == ["body", "body", "body", "service"]
    initial = [row("1 Basics", 1, 90), row("Pedro A. de Miguel", 91, 100)]
    assert _roles(initial) == ["body", "service"]
    article = [row("1 Basics", 1, 90), row("A Brief Guide", 91, 100)]
    assert _roles(article) == ["body", "service"]


def test_the_book_s_heads_take_its_running_heads_and_rising_folios_but_not_a_number_ending_the_text():
    def page(n, *texts):
        return [SimpleNamespace(text=t) for t in ("PostgreSQL Notes", *texts, f"— {n - 4} —")]
    lines = {n: page(n, "Body text", "and 42 more") for n in range(5, 9)}
    lines[9] = [SimpleNamespace(text=t) for t in ("PostgreSQL Notes", "SELECT length('a')", "1")]
    heads = running_heads.layer_heads(lines)
    assert heads[6] == ["PostgreSQL Notes", "— 2 —"] and heads[9] == ["PostgreSQL Notes"]


@needs_db
def test_a_garbled_page_is_read_by_recognition_like_a_page_without_a_layer(stand, tmp_path):
    from orm.catalogue import Book
    from orm.db import Session

    book, _ = intake.register([(build(tmp_path / "g.pdf", [text_page(f"Page {n}") for n in range(1, 5)]), "g.pdf")])
    with Session() as session:
        session.get(Book, book).text_layer = {"with_layer": 3, "without_layer": [], "garbled": [3]}
        session.commit()
    assert assemble.scanned_pages(book) == frozenset({3})
    assert [(a, b, regime) for _, a, b, regime in assemble.ranges(book, 1, 4)] == [
        (1, 2, "text_pdf"), (3, 3, "scan"), (4, 4, "text_pdf")]


def test_headings_inside_a_chapter_at_the_deepest_level_stay_paragraphs_and_the_chapter_writes():
    from writers import markdown

    blocks = [PageMarker(book_page=1, file_ord=0, file_page=1), Heading(text="Inner", level=1, level_source="docling"),
              Paragraph(text="Body.")]
    out, counts = passes.piece_levels(blocks, 5, [])
    assert counts["headings_flattened"] == 1 and isinstance(out[1], Paragraph) and out[1].text == "Inner"
    from document.model import Piece
    assert "Inner" in markdown.piece(Piece(ord=1, title="Deep", level=5, first_page=1, last_page=1, blocks=out))


def test_a_node_takes_the_heading_closest_to_its_title_and_a_heading_goes_to_one_node():
    blocks = [Heading(text="1.4 Description", level=2, level_source="docling"),
              Heading(text="1.4.1 Description", level=3, level_source="docling")]
    assert passes.pins(blocks, ["1.4.1 Description", "1.4 Description"]) == [1, 0]
    counts = {}
    assert passes.pins(blocks[:1], ["1.4 Description", "1.4 Description"], counts) == [0, None]
    assert counts == {"pins_contested": 1}
    out, counts = passes.piece_levels(blocks, 1, [("1.4.1 Description", 3)])
    assert [(h.level, h.level_source) for h in out] == [(1, "docling"), (2, "structure")]


def test_a_tail_counts_as_cut_from_the_own_re_read_only_where_that_re_read_holds_the_boundary_page(monkeypatch):
    marked = {"docling": [PageMarker(book_page=4, file_ord=0, file_page=4), Paragraph(text="before")],
              "mineru": [PageMarker(book_page=4, file_ord=0, file_page=4), Paragraph(text="before"),
                         PageMarker(book_page=5, file_ord=0, file_page=5), Paragraph(text="tail")]}
    monkeypatch.setattr(assemble, "_kept", lambda book_id, f, a, b, regime, engine, *rest: engine)
    monkeypatch.setattr(assemble.reading, "adapt",
                        lambda engine, kept, **kw: SimpleNamespace(blocks=list(marked[kept]), furniture=[]))
    monkeypatch.setattr(assemble.passes, "recognised", lambda reads, *rest: ([], {}, {}))
    monkeypatch.setattr(assemble, "_kept_figures", lambda path, blocks, keep: blocks)
    got = assemble.Assembled(piece=None, markdown="")
    f = SimpleNamespace(ord=0, first_page=1, pages=5, file_path="b.pdf")
    assemble._range_blocks(1, f, 4, 5, "scan", ["en"], got, got.counts, None, {"scan_engine": "mineru"},
                           boundaries=[passes.Boundary(page=5, title="Next", tail=True)], neighbour={})
    assert got.counts["boundary_own_reading"] == 1


def test_a_title_every_chapter_repeats_is_pinned_on_its_node_s_own_pages_never_a_namesake_s():
    def page(n):
        return PageMarker(book_page=n, file_ord=0, file_page=n)

    quiz = "Контрольные вопросы"
    head = Heading(text=quiz, level=2, level_source="docling")
    blocks = [page(27), Paragraph(text="text"), page(35), head, page(68), head]
    spans = [(27, 27), (35, 35), (68, 68)]
    assert passes.pins(blocks, [quiz] * 3, None, spans) == [None, 3, 5]
    assert passes.pins(blocks, [quiz] * 3) == [3, 5, None]
    nested = [page(5), head, page(6), head]
    assert passes.pins(nested, [quiz] * 2, None, [(5, 7), (5, 5)]) == [1, 3]
