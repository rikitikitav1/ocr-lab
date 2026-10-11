from types import SimpleNamespace

from assembly import passes
from document.model import Figure, Heading, PageMarker, Paragraph, Where
from stages import assemble, intake, running_heads

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

    def row(kind, title, first, last):
        return {"kind": kind, "title": title, "level": 1, "first_page": first, "last_page": last}

    rows = [row("front_matter", "Cover", 1, 1), row("chapter", "Content list", 2, 4), row("chapter", "One", 5, 8)]
    assert [c["title"] for c in assemble.chapters_of(rows, frozenset({2, 3, 4}))] == ["Cover", "One"]


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

    assert assemble._cover([row("front_matter", 1), row("chapter", 2)]) == {1}
    assert assemble._cover([row("chapter", 1), row("chapter", 5)]) == frozenset()


def test_unnumbered_chapters_on_both_edges_of_the_numbered_run_are_service():
    def row(title, first):
        return {"kind": "chapter", "title": title, "level": 1, "first_page": first, "last_page": first}

    book = [row("Preface", 1), row("Благодарности", 2), {**row("1 Basics", 3), "last_page": 95}, row("Afterword", 96)]
    book[-1]["last_page"] = 100
    roles = [c["role"] for c in assemble.chapters_of(book)]
    assert roles == ["service", "service", "body", "service"]
    assert {c["role"] for c in assemble.chapters_of([row("Preface", 1), row("Basics", 2)])} == {"body"}
    roman = [row("Foreword", 1), row("Глава IV", 2)]
    roman[-1]["last_page"] = 100
    assert assemble.chapters_of(roman)[0]["role"] == "service"
    words = [row("What I Learned", 1), row("C Programming", 2), row("1 Basics", 3)]
    words[-1]["last_page"] = 100
    assert [c["role"] for c in assemble.chapters_of(words)] == ["service", "service", "body"]
    parts = [row("Preface", 1), row("Часть I Основы", 3), row("Глава", 4), row("Часть II Дальше", 6)]
    parts[-1]["last_page"] = 100
    assert [c["role"] for c in assemble.chapters_of(parts)] == ["service", "body", "body", "body"]
    late = [row("Preface", 1), row("Processes", 2)] + [row(f"Topic {n}", 40 + n) for n in range(1, 3)]
    late[-1]["last_page"] = 100
    assert {c["role"] for c in assemble.chapters_of(late)} == {"body"}
    early = [row("1 Basics", 1), row("2 More", 10), row("Appendix", 20)]
    early[-1]["last_page"] = 100
    assert [c["role"] for c in assemble.chapters_of(early)] == ["body", "body", "body"]


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


def test_chapters_are_chapter_rows_with_their_sections_and_a_part_s_own_pages():
    def row(kind, title, level, first, last):
        return {"kind": kind, "title": title, "level": level, "first_page": first, "last_page": last}

    rows = [row("front_matter", "Front matter", 1, 1, 4), row("part", "Part I", 1, 5, 40),
            row("chapter", "One", 2, 7, 20), row("section", "1.1", 3, 9, 20), row("chapter", "Two", 2, 21, 40),
            row("part", "Part II", 1, 41, 60), row("chapter", "Three", 2, 41, 60)]
    got = [(c["title"], c["first_page"], c["last_page"], c["subs"]) for c in assemble.chapters_of(rows)]
    assert got == [("Front matter", 1, 4, []), ("Part I", 5, 6, []), ("One", 7, 20, [("1.1", 3)]),
                   ("Two", 21, 40, []), ("Three", 41, 60, [])]


def test_a_heading_deeper_than_the_writer_allows_is_demoted_and_counted_never_raised():
    blocks = [Heading(text="Intro", level=2, level_source="docling"), Heading(text="1.1 Basics", level=3,
              level_source="docling"), Heading(text="deep", level=5, level_source="docling")]
    out, counts = passes.chapter_levels(blocks, 2, [("1.1 Basics", 3)])
    assert [(h.level, h.level_source) for h in out] == [(1, "docling"), (1, "toc"), (3, "docling")]
    assert counts == {"headings_from_toc": 1, "headings_demoted": 1, "headings_flattened": 0}


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
    markers = [(b.file_ord, b.file_page, b.book_page) for b in got.chapter.blocks if isinstance(b, PageMarker)]
    assert markers == [(0, 2, 2), (1, 1, 3)]
    assert any(isinstance(b, Paragraph) and "Second file" in b.text for b in got.chapter.blocks)
    assert "<!-- chapter ord=1 pages=2-3 role=body -->\n\n### Chapter\n\n#### Deep heading" in got.markdown
    assert [name for name, _ in got.steps[0]["steps"]][0] == "referee" and "furniture_docling" in got.counts
    assert set(got.pages) == {2, 3} and all(set(p["scores"]) == {"docling", "mineru"} for p in got.pages.values())
    assert got.counts.get("pages_docling", 0) + got.counts.get("pages_mineru", 0) == 2


def test_chapters_under_a_part_come_out_of_the_toc_rows_as_chapters():
    from stages.toc import collect
    from stages.toc.sources import Entry

    entries = [Entry("Part One", 1, 5), Entry("What Is Security Engineering?", 2, 7), Entry("Goals", 3, 9),
               Entry("Protocols", 2, 30), Entry("Part Two", 1, 60), Entry("Cryptography", 2, 62),
               Entry("Afterword", 1, 90)]
    chapters = assemble.chapters_of(collect.rows(entries, "bookmarks", 100))
    assert [(c["title"], c["first_page"], c["last_page"], c["subs"]) for c in chapters] == [
        ("Part One", 5, 6, []), ("What Is Security Engineering?", 7, 29, [("Goals", 3)]), ("Protocols", 30, 59, []),
        ("Part Two", 60, 61, []), ("Cryptography", 62, 89, []), ("Afterword", 90, 100, [])]


def test_the_chapter_title_set_again_on_its_first_page_goes():
    blocks = [PageMarker(book_page=1, file_ord=0, file_page=1), Heading(text="Chapter 7: COALESCE", level=1,
              level_source="docling"), Paragraph(text="Coalesce returns the first non null argument.")]
    out, dropped = passes.without_title(blocks, "Chapter 7: COALESCE")
    assert dropped == 1 and [type(b).__name__ for b in out] == ["PageMarker", "Paragraph"]
    assert passes.without_title(blocks, "Chapter 8: INSERT")[1] == 0


def test_lettered_appendices_count_as_numbered_and_a_lone_article_does_not():
    def row(title, first, last):
        return {"kind": "chapter", "title": title, "level": 1, "first_page": first, "last_page": last}

    book = [row("1 Basics", 1, 80), row("Appendix A: Keywords", 81, 90), row("Credits", 91, 92), row("Index", 93, 100)]
    assert [c["role"] for c in assemble.chapters_of(book)] == ["body", "body", "service", "service"]
    bare = [row("1 Basics", 1, 80), row("A Debugging", 81, 85), row("B Analysis", 86, 95), row("Index", 96, 100)]
    assert [c["role"] for c in assemble.chapters_of(bare)] == ["body", "body", "body", "service"]
    initial = [row("1 Basics", 1, 90), row("Pedro A. de Miguel", 91, 100)]
    assert [c["role"] for c in assemble.chapters_of(initial)] == ["body", "service"]
    article = [row("1 Basics", 1, 90), row("A Brief Guide", 91, 100)]
    assert [c["role"] for c in assemble.chapters_of(article)] == ["body", "service"]


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
    out, counts = passes.chapter_levels(blocks, 5, [])
    assert counts["headings_flattened"] == 1 and isinstance(out[1], Paragraph) and out[1].text == "Inner"
    from document.model import Chapter
    assert "Inner" in markdown.chapter(Chapter(ord=1, title="Deep", level=5, first_page=1, last_page=1, blocks=out))
