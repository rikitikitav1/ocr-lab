import pytest
from job_signals import Final
from stages import intake
from stages.toc import collect, pages
from stages.toc.sources import Entry, numbering, printed_contents

from tests.fixtures import FILLER, build, text_page
from tests.real_db import needs_db

pytestmark = needs_db

OFFSET = 2


def _entry(text, page=None, x=30, size=10):
    leader = f" . . . . . . . . . . {page}" if page is not None else ""
    return {"text": text + leader, "x": x, "size": size}


def contents() -> dict:
    return {"lines": [
        {"text": "Contents", "size": 16},
        _entry("Part I Basics", size=12, x=120),
        _entry("Chapter 1 Getting started", 1),
        _entry("What the stand does", 1, x=50),
        _entry("Chapter 2 A title long enough that the printer", None),
        _entry("had to wrap it", 3),
        _entry("Where pages come from", 4, x=50),
        _entry("Chapter 3 The end", 5),
    ]}


def body(*titles) -> dict:
    return {"lines": [*titles, FILLER[:90], FILLER[90:180]]}


@pytest.fixture
def book(stand, tmp_path):
    path = build(tmp_path / "c.pdf", [
        text_page("A book about stands"), contents(),
        body("Chapter 1 Getting started", "What the stand does"), body("More words"),
        body("Chapter 2 A title long enough that the printer had to wrap it"), body("Where pages come from"),
        body("Chapter 3 The end"),
    ])
    book_id, _ = intake.register([(path, "c.pdf")])
    return book_id


def test_printed_contents_reads_levels_and_wrapped_titles(book):
    found = printed_contents.read(intake.files_of(book), None)
    assert found.notes["pages"] == [2]
    got = [(e.title, e.level, e.printed) for e in found.entries]
    assert got == [("Part I Basics", 1, None), ("Chapter 1 Getting started", 2, "1"),
                   ("What the stand does", 3, "1"),
                   ("Chapter 2 A title long enough that the printer had to wrap it", 2, "3"),
                   ("Where pages come from", 3, "4"), ("Chapter 3 The end", 2, "5")]


def test_printed_pages_are_placed_by_the_offset_that_fits_most_titles():
    text = {p: pages.norm(t) for p, t in {3: "Chapter 1 Getting started", 5: "Chapter 2 Two",
                                          6: "where pages come from", 7: "chapter 3 the end"}.items()}
    entries = [Entry("Part I", 1), Entry("Chapter 1 Getting started", 2, printed="1"),
               Entry("Chapter 2 Two", 2, printed="3"), Entry("Where pages come from", 3, printed="4"),
               Entry("Chapter 3 The end", 2, printed="5"), Entry("Not printed in the text", 2, printed="6")]
    notes = pages.place(entries, text, 9)
    assert notes["offset"] == OFFSET and notes["verified"] == 4 and notes["unverified"] == 1
    assert [e.page for e in entries] == [3, 3, 5, 6, 7, 8]


def test_chapter_ranges_end_where_the_next_entry_at_their_level_starts():
    entries = [Entry("Part I", 1, 3), Entry("Chapter 1", 2, 3), Entry("Section", 3, 4), Entry("Chapter 2", 2, 5),
               Entry("Chapter 3", 2, 7)]
    got = [(r["title"], r["first_page"], r["last_page"], r["kind"]) for r in collect.rows(entries, "x", 9)]
    assert got == [("Part I", 3, 9, "part"), ("Chapter 1", 3, 4, "chapter"), ("Section", 4, 4, "section"),
                   ("Chapter 2", 5, 6, "chapter"), ("Chapter 3", 7, 9, "chapter")]


def test_a_book_without_bookmarks_takes_its_printed_contents_and_stores_the_offset(book):
    from orm.catalogue import Book
    from orm.db import Session

    collect.collect(book)
    with Session() as session:
        stored = session.get(Book, book)
        assert stored.page_offset == OFFSET and stored.stage == "ready"
    version = collect.current_version(book)
    assert version is not None and collect.collect(book) == version.id


@pytest.fixture
def no_headings(monkeypatch):
    from stages.toc import scan

    monkeypatch.setattr(scan, "recognise", lambda book_id, book_pages, cached_only=False: {p: {} for p in book_pages})


def test_a_short_book_without_contents_is_one_chapter(stand, tmp_path, no_headings):
    path = build(tmp_path / "s.pdf", [text_page("Once upon a time"), text_page("The end")])
    book_id, _ = intake.register([(path, "a-tale.pdf")])
    source, entries, _ = collect.choose(book_id)
    assert source == "whole_book" and [(e.title, e.page) for e in entries] == [("a-tale", 1)]


def test_a_long_book_without_contents_fails_as_structure_not_recognised(stand, tmp_path, no_headings):
    path = build(tmp_path / "l.pdf", [text_page(f"Page {n}") for n in range(101)])
    book_id, _ = intake.register([(path, "long.pdf")])
    with pytest.raises(Final, match="101 pages.*headings no group"):
        collect.choose(book_id)


def test_a_book_with_no_contents_but_labelled_chapters_takes_them_however_long(stand, tmp_path, monkeypatch,
                                                                              no_headings):
    path = build(tmp_path / "e.pdf", [text_page(f"Page {n}") for n in range(120)])
    book_id, _ = intake.register([(path, "ebook.pdf")])
    found = [Entry(f"Chapter {n}. Topic", 1, 20 * n, source="numbering") for n in range(1, 4)]
    monkeypatch.setattr(numbering, "read", lambda files, skip, lines: numbering.SourceToc("numbering", found))
    source, entries, _ = collect.choose(book_id)
    assert source == "numbering" and [(e.title, e.page) for e in entries] == [(e.title, e.page) for e in found]
    monkeypatch.setattr(numbering, "read", lambda files, skip, lines: numbering.SourceToc("numbering", found[:2]))
    with pytest.raises(Final):
        collect.choose(book_id)


def test_ignored_bookmarks_leave_the_chapters_to_the_label_knob(stand, tmp_path):
    pages = [text_page("Cover", bookmark="IMG_0001.jpg"), text_page("Lesson one", "Greetings", bookmark="IMG_0002.jpg"),
             text_page("Read the lesson", bookmark="IMG_0003.jpg"), text_page("Lesson two", bookmark="IMG_0004.jpg")]
    book_id, _ = intake.register([(build(tmp_path / "r.pdf", pages), "r.pdf")])
    assert collect.choose(book_id)[0] == "bookmarks"
    book_id, _ = intake.register([(build(tmp_path / "k.pdf", [*pages, text_page("The end")]), "k.pdf")],
                                 {"toc.ignore_bookmarks": True, "toc.chapter_label": "lesson"})
    source, entries, evidence = collect.choose(book_id)
    assert source == "labels" and [(e.title, e.page) for e in entries] == [("Lesson one", 2), ("Lesson two", 4)]
    assert "ignored" in evidence["bookmarks"]["failed"]


def test_bookmarks_win_over_printed_contents(stand, tmp_path):
    path = build(tmp_path / "b.pdf", [text_page("Title"), contents(), text_page("One", bookmark="One"),
                                      text_page("Two", bookmark="Two")])
    book_id, _ = intake.register([(path, "b.pdf")])
    source, entries, _ = collect.choose(book_id)
    assert source == "bookmarks" and [(e.title, e.page) for e in entries] == [("One", 3), ("Two", 4)]


@pytest.mark.parametrize("title,depth", [("Часть II. Болезни", -1), ("Chapter 3 Types", 0), ("1.2. Нос", 1),
                                         ("4.4.1 Hearing", 2), ("Introduction", None), ("Part One", -1),
                                         ("Chapter XII. End", 0),
                                         ("Глава первая", 0)])
def test_title_depth(title, depth):
    assert numbering.title_depth(title) == depth


def test_a_label_is_cut_from_a_title_only_when_its_number_is_well_formed():
    import numerals
    from stages.toc.pages import words

    assert [words(t) for t in ("Civil Society", "CIVIL WAR", "IV. Analysis", "Part IV The End", "2.1 Intro",
                               "D. Conclusion", "part ii: oop")] == [
        "civil society", "civil war", "analysis", "the end", "intro", "d conclusion", "oop"]
    assert [numerals.value(t) for t in ("XIV", "xiv", "MCMXC", "12", "IIII", "CIVIL", "Xiv")] == [
        14, 14, 1990, 12, None, None, None]


def test_a_label_in_running_text_is_not_a_chapter():
    assert numbering._match("Глава 1 начинается с определения понятия", True, False) is None
    assert numbering._match("part of a group.", True, True) is None
    assert numbering._match("ГЛАВА 1 Большие данные", True, True)[:2] == ("chapter", (1,))
    assert numbering._match("2.998e8", False, False) is None


def test_bold_sets_a_label_apart_only_when_the_body_is_not_bold():
    from pdf import Line

    def book(body_bold):
        prose = [Line("ordinary words of the body " * 3, 30, 40 + 14 * i, 10, body_bold) for i in range(1, 6)]
        return {5: [Line("Part 1 of the Civil Code regulates persons", 30, 40, 10, True), *prose]}

    assert [c[2] for c in numbering._candidates(book(False), set())] == ["Part 1 of the Civil Code regulates persons"]
    assert numbering._candidates(book(True), set()) == []


def test_running_heads_are_left_out_of_the_text_titles_are_found_in():
    from pdf import Line

    def page(*texts):
        return [Line(t, 30, 40 + 14 * i, 10, False) for i, t in enumerate(texts)]

    lines = {p: page(f"{p} Chapter 2 Glottis", "body text", "more body") for p in range(10, 14)}
    lines[9] = page("Chapter 2 Glottis", "body text")
    text = pages.page_text(lines, set())
    assert "chapter2glottis" in text[9] and all("chapter2glottis" not in text[p] for p in range(10, 14))


def test_an_unfound_title_follows_the_offset_of_the_last_found_one():
    text = {2: pages.norm("Chapter one"), 11: pages.norm("Chapter three")}
    entries = [Entry("Chapter one", 1, printed="1"), Entry("Missing in the text", 1, printed="3"),
               Entry("Chapter three", 1, printed="6"), Entry("Also missing", 1, printed="8")]
    pages.place(entries, text, 20)
    assert [e.page for e in entries] == [2, 4, 11, 13]


def test_a_part_title_is_placed_on_its_own_page_before_the_blank_one():
    text = {5: pages.norm("PART I Setting the Stage"), 7: pages.norm("CHAPTER 1 Introduction")}
    entries = [Entry("Part I. Setting the Stage", 1), Entry("Introduction", 2, printed="5"),
               Entry("Table of Contents", 1, printed="v")]
    pages.place(entries, text, 20)
    assert [e.page for e in entries] == [5, 7, None]


def _layout(*blocks):
    return {"blocks": [{"type": kind, "content": content} for kind, content in blocks]}


def _index(*lines):
    return ("index", [{"type": "text", "content": [{"type": "text", "content": line}]} for line in lines])


def test_a_numbered_table_with_dot_leaders_is_not_contents():
    from stages.toc import scan

    table = _index("1-a Episcopo 28", "2-a Notarrio 100", "3-a Iudici 50", "4-a Incassatori 40", "11 Scripturis 24",
                   "12 Necessitatibus 326", "Summa 868", "Summa Summarrum 4729")
    contents = _index("Prefata 2", "I. Pozitia 3", "II. Locuitorii 9", "1. Nationalitatea 9", "Religiunea 12")
    found, pages = scan.entries({103: _layout(table), 128: _layout(contents)}, 129)
    assert pages == [128] and [e.title for e in found][:2] == ["Prefata", "I. Pozitia"]


def test_a_lettered_run_keeps_c_and_v_as_letters_unless_the_list_has_longer_roman_numerals():
    from stages.toc import scan
    from stages.toc.sources import Entry

    found = [Entry(t, None) for t in ["A. Scope", "B. Terms", "C. Sources", "D. Courts", "V. Venue"]]
    scan.levels(found)
    assert {e.level for e in found} == {1}


def test_levels_follow_numbering_styles_whatever_the_language():
    from stages.toc import scan
    from stages.toc.sources import Entry

    titles = ["Prefata", "I. Pozitia", "II. Locuitorii", "1. Nationalitatea", "a) Biserica", "b) Scoala",
              "III. Ocupatiunea", "1. Agricultura", "2. Vinicultura", "VI. Administratia"]
    found = [Entry(t, None) for t in titles]
    scan.levels(found)
    assert [e.level for e in found] == [1, 1, 1, 2, 3, 3, 1, 2, 2, 1]
    titles = ["Cuvânt introductiv", "CAPITOLUL I. Repere", "a) Epoca veche", "b) Perioada", "CAPITOLUL II. Cadrul",
              "a) Aşezarea", "CAPITOLUL IV. Economia", "1. De la economia", "a) Gospodării", "2. Dezvoltarea",
              "Windows 95 tips"]
    found = [Entry(t, None) for t in titles]
    scan.levels(found)
    assert [e.level for e in found] == [1, 1, 2, 2, 1, 2, 1, 2, 3, 2, 3]


def test_a_scans_recognised_contents_become_entries_with_levels_and_an_offset():
    from stages.toc import scan

    recognised = {3: _layout(("header", "Contents"), _index("Introduction 1", "1. Containers and their", "images 11",
                                                            "Why images 12", "2. Pods 20")),
                  9: _layout(("page_number", "3")), 10: _layout(("page_number", "4")),
                  20: _layout(("page_number", "14")), 21: _layout(("page_number", "1"))}
    found, contents_pages = scan.entries(recognised, 100)
    scan.levels(found)
    assert contents_pages == [3]
    assert [(e.title, e.level, e.printed) for e in found] == [
        ("Introduction", 1, "1"), ("1. Containers and their images", 1, "11"), ("Why images", 2, "12"),
        ("2. Pods", 1, "20")]
    assert scan.folio_offset(recognised) == (6, 3)


def test_chapter_files_are_chapters_and_a_part_title_page_gives_the_part(stand, tmp_path):
    from stages.toc.sources import files

    def opening(*lines):
        return {"lines": [*lines, FILLER[:90]]}

    one = build(tmp_path / "1.pdf", [opening({"text": "PART", "size": 18}, {"text": "One", "size": 40}),
                                     opening({"text": "CHAPTER", "size": 14}, {"text": "Threats", "size": 22}),
                                     text_page("more")])
    two = build(tmp_path / "2.pdf", [opening({"text": "Protocols", "size": 22}), text_page("more")])
    book_id, _ = intake.register([(one, "1.pdf"), (two, "2.pdf")])
    found = files.read(intake.files_of(book_id))
    assert [(e.title, e.level, e.page) for e in found.entries] == [("Part One", 1, 1), ("Threats", 2, 2),
                                                                    ("Protocols", 2, 4)]
    source, _, _ = collect.choose(book_id)
    assert source == "files"


def test_the_root_bookmark_knob_lifts_the_chapters_to_the_top():
    entries = [Entry("The book", 1, 1), Entry("One", 2, 2), Entry("Two", 2, 5), Entry("Two.1", 3, 6),
               Entry("Translator's note", 1, 9)]
    assert [(e.title, e.level) for e in collect.without_root(entries)] == [
        ("One", 1), ("Two", 1), ("Two.1", 2), ("Translator's note", 1)]
    flat = [Entry("A", 1, 1), Entry("B", 1, 2)]
    assert collect.without_root(flat) == flat


def test_chapter_files_are_ordered_by_the_number_they_print_biggest(tmp_path):
    from stages import file_order

    def chapter(name, mark):
        lines = ([{"text": mark, "size": 20}] if mark else []) + [{"text": f"About {name}", "size": 14}]
        return build(tmp_path / f"{name}.pdf", [{"lines": [*lines, FILLER[:90]]}])

    given = [(chapter(n, m), n) for n, m in (("app-b", "B"), ("ten", "10"), ("two", "2"), ("preface", None),
                                               ("app-a", "A"))]
    ordered, marks = file_order.by_number(given)
    assert [name for _, name in ordered] == ["preface", "two", "ten", "app-a", "app-b"]
    assert marks == [None, "2", "10", "A", "B"]


def test_a_title_with_a_broken_glyph_stays_on_its_offset_page():
    text = {2: pages.norm("Первая глава книги"), 3: pages.norm("Вторая глава книги"),
            5: pages.norm("7.3. \x81азвертывание в облаке"), 6: pages.norm("7.3. Развертывание в облаке 6")}
    entries = [Entry("Первая глава книги", 1, printed="2"), Entry("Вторая глава книги", 1, printed="3"),
               Entry("7.3. Развертывание в облаке", 2, printed="5")]
    pages.place(entries, text, 9)
    assert [e.page for e in entries] == [2, 3, 5]


def _e(title, level, page, verified=True):
    return Entry(title, level, page, verified=verified)


def test_reconcile_takes_the_confirmed_printed_contents_as_base_and_bookmarks_add_what_it_lacks():
    from stages.toc import reconcile

    printed = [_e("Chapter 1 Start", 1, 3), _e("Basics", 2, 4), _e("Chapter 2 Middle", 1, 10)]
    marks = [_e("1 Start", 1, 3), _e("Chapter 2 Middle", 1, 12), _e("Chapter 3 End", 1, 20), _e("Index", 2, 30)]
    base, merged, report = reconcile.reconcile({"printed_contents": printed, "bookmarks": marks})
    assert base == "printed_contents"
    assert [(e.title, e.level, e.page) for e in merged] == [
        ("Chapter 1 Start", 1, 3), ("Basics", 2, 4), ("Chapter 2 Middle", 1, 10), ("Chapter 3 End", 1, 20)]
    assert merged[2].votes["printed_contents"]["page"] == 10 and merged[2].source == "bookmarks"
    assert set(merged[0].votes) == {"printed_contents", "bookmarks"}
    assert report["conflicts"] == [{"title": "Chapter 2 Middle", "printed_contents": 10, "bookmarks": 12}]


def test_reconcile_falls_back_to_bookmarks_when_the_printed_pages_are_unconfirmed():
    from stages.toc import reconcile

    printed = [_e("One", 1, 3, False), _e("Two", 1, 9, False), _e("Three", 1, 15, True)]
    marks = [_e("One", 1, 4), _e("Two", 1, 10)]
    base, _, _ = reconcile.reconcile({"printed_contents": printed, "bookmarks": marks})
    assert base == "bookmarks"


def test_numbering_confirms_but_never_adds_alone():
    from stages.toc import reconcile

    marks = [_e("Chapter 1", 1, 3), _e("Chapter 2", 1, 9)]
    counted = [_e("Chapter 1", 1, 3), _e("3.2 Seen in a reference", 2, 5)]
    _, merged, report = reconcile.reconcile({"bookmarks": marks, "numbering": counted})
    assert [e.title for e in merged] == ["Chapter 1", "Chapter 2"] and report["matched"]["numbering"] == 1


def test_levels_come_from_bookmarks_and_unmatched_printed_entries_follow_their_scale():
    from stages.toc import reconcile

    printed = [_e("Chapter 1 Start", 2, 3), _e("Basics", 2, 4), _e("Only printed", 3, 5),
               _e("Chapter 2 Middle", 2, 10)]
    marks = [_e("Chapter 1 Start", 1, 3), _e("Basics", 2, 4), _e("Chapter 2 Middle", 1, 10),
             _e("Chapter 3 End", 1, 20)]
    _, merged, report = reconcile.reconcile({"printed_contents": printed, "bookmarks": marks})
    assert [(e.title, e.level, e.page) for e in merged] == [
        ("Chapter 1 Start", 1, 3), ("Basics", 2, 4), ("Only printed", 2, 5), ("Chapter 2 Middle", 1, 10),
        ("Chapter 3 End", 1, 20)]
    assert report["levels_from_bookmarks"]["moved"] >= 2


def test_the_pages_before_the_first_entry_become_a_front_matter_section():
    from types import SimpleNamespace

    entries = [Entry("Chapter 1", 1, 5, source="bookmarks"), Entry("Chapter 2", 1, 9, source="bookmarks")]
    got = collect.rows(collect.with_front_matter(entries, [SimpleNamespace(file_name="a-book.pdf")]), "bookmarks", 12)
    assert [(r["title"], r["first_page"], r["last_page"], r["kind"]) for r in got] == [
        ("a-book", 1, 4, "front_matter"), ("Chapter 1", 5, 8, "chapter"), ("Chapter 2", 9, 12, "chapter")]
    assert collect.with_front_matter([Entry("Starts at once", 1, 1)], []) == [Entry("Starts at once", 1, 1)]


def test_numbering_adds_a_labelled_part_alone_but_not_a_bare_number():
    from stages.toc import reconcile

    marks = [_e("Introduction", 1, 3), _e("Access to Knowledge", 1, 18)]
    counted = [Entry("PART TWO THE EMERGENCE", 1, 99, evidence="labelled part number 2", verified=True),
               Entry("IV", 1, 120, evidence="chapter number 4", verified=True)]
    _, merged, _ = reconcile.reconcile({"bookmarks": marks, "numbering": counted})
    assert [e.title for e in merged] == ["Introduction", "Access to Knowledge", "PART TWO THE EMERGENCE"]


def test_a_numbered_title_on_the_same_page_as_a_longer_bookmark_is_one_entry():
    from stages.toc import reconcile

    marks = [_e("Background Introduced by Michael Stonebraker", 1, 5), _e("Languages Introduced by Joe", 1, 30)]
    counted = [Entry("Chapter 1: Background", 1, 5, evidence="labelled chapter number 1", verified=True)]
    _, merged, _ = reconcile.reconcile({"bookmarks": marks, "numbering": counted})
    assert [e.title for e in merged] == ["Background Introduced by Michael Stonebraker", "Languages Introduced by Joe"]


def test_a_toc_that_needs_the_card_on_the_cpu_lane_goes_to_the_gpu_lane(monkeypatch):
    import job_queue
    from engines import card
    from job_handlers import book

    def needs_card(*a, **kw):
        raise card.WrongLane("ollama is needed")

    handed = []
    monkeypatch.setattr(book.collect, "scanned", lambda book_id: False)
    monkeypatch.setattr(book.collect, "needs_raster", lambda book_id: False)
    monkeypatch.setattr(book.collect, "collect", needs_card)
    monkeypatch.setattr(job_queue, "enqueue", lambda type, options, **kw: handed.append((type, options)) or 7)
    result = book.run_toc({"book_id": 3, "force": True, "_job_id": 1})
    assert result["toc_scan_job_id"] == 7
    assert handed == [("toc_scan", {"book_id": 3, "what": ["toc"], "force": True, "run": False})]


def test_a_forced_recollection_forces_every_stage_it_chains(monkeypatch):
    import job_queue
    from job_handlers import book

    handed = []
    monkeypatch.setattr(job_queue, "enqueue", lambda type, options, **kw: handed.append((type, options)) or 1)
    monkeypatch.setattr(job_queue, "is_cancelled", lambda id: False)
    monkeypatch.setattr(book.intake, "probe", lambda book_id: {"text_layer": {"pages": 1, "without_layer": []},
                                                               "toc_sources": []})
    book.run_intake({"book_id": 3, "then": ["metadata", "toc"], "force": True, "_job_id": 1})
    monkeypatch.setattr(book.resolve, "current_version", lambda book_id: None)
    monkeypatch.setattr(book.resolve, "collect", lambda *a, **kw: 9)
    book.run_metadata({"book_id": 3, "what": ["metadata", "toc"], "force": True, "_job_id": 2})
    assert [(t, o["force"]) for t, o in handed] == [("metadata", True), ("toc", True)]



def test_labelled_chapters_stand_as_a_toc_only_in_order_and_pages_apart():
    def chapters(*pairs):
        return [Entry(title, 1, page) for title, page in pairs]

    book = chapters(("Chapter 1. Meet", 22), ("Chapter 2. Install", 48), ("Chapter 37 see there", 60),
                    ("Chapter 3. Use", 91), ("Chapter 4. Run", 135), ("Chapter 5. Tune", 180), ("Chapter 6. End", 200),
                    ("Chapter 7. More", 230), ("Chapter 8. Last", 260), ("Chapter 9. After", 300),
                    ("Chapter 10. Coda", 330), ("Chapter 11. Notes", 360))
    assert collect._labelled(book) == 12
    listed = chapters(("PART ONE", 7), ("PART TWO", 8), ("PART FOUR", 9), ("PART THREE", 223))
    assert collect._labelled(listed) == 0
    shuffled = chapters(("Chapter 3. C", 10), ("Chapter 1. A", 40), ("Chapter 2. B", 70))
    assert collect._labelled(shuffled) == 0
    assert [e.title for e in collect._out_of_turn(book)] == ["Chapter 37 see there"]
    parted = chapters(("Part 1. A", 10), ("Chapter 1. a", 11), ("Chapter 2. b", 30), ("Part 2. B", 50),
                      ("Chapter 3. c", 51), ("Chapter 4. d", 70), ("Part 3. C", 90), ("Chapter 5. e", 91),
                      ("Chapter 6. f", 110), ("Part 4. D", 130), ("Chapter 7. g", 131), ("Chapter 8. h", 150))
    assert collect._labelled(parted) == 12



def test_the_books_contents_beats_a_longer_chapter_contents_and_a_year_is_no_page():
    def block(*printed):
        return [(Entry(f"t{i}", None, printed=p), None, 1) for i, p in enumerate(printed)]

    book = block("1", "99", "113", "409")
    chapter = block("4", "5", "9", "11", "12", "21", "25", "30", "87", "2018")
    assert printed_contents._reach(book, 420) > printed_contents._reach(chapter, 420)


def test_a_plate_both_without_a_layer_and_garbled_counts_once_toward_a_scan():
    from types import SimpleNamespace

    from stages.toc import scan

    plates = list(range(1, 27))
    book = SimpleNamespace(pages=100, text_layer={"without_layer": plates, "garbled": plates})
    assert not scan.is_scan(book)


def test_a_label_and_one_word_at_a_page_s_top_opens_a_chapter_and_a_label_in_a_phrase_does_not():
    from stages.toc.sources import labelled

    heads = {2: ["درس اول", "معرفی کردن"], 5: ["درس خواندن کلاس"], 9: ["درس دوم"], 12: ["درس 3"], 16: ["درس سوّم"],
             56: [". درس هفتم"]}
    got = labelled.read(heads, "درس", "a recognised page")
    assert [(e.title, e.page) for e in got.entries] == [("درس اول", 2), ("درس دوم", 9), ("درس سوّم", 16),
                                                        ("درس هفتم", 56)]
    assert labelled.read({2: ["درس اول"]}, "درس", "a recognised page").failed


def test_ignored_bookmarks_neither_stop_a_raster_read_nor_serve_as_the_eval_s_gold(stand, tmp_path):
    from evaluation import toc_run

    pages = [text_page("Cover", bookmark="IMG_0001.jpg"), text_page("Text", bookmark="IMG_0002.jpg"),
             text_page("More text", bookmark="IMG_0003.jpg")]
    kept, _ = intake.register([(build(tmp_path / "kept.pdf", pages), "kept.pdf")])
    assert not collect.needs_raster(kept) and len(toc_run._gold(kept)) == 3
    ignored, _ = intake.register([(build(tmp_path / "ign.pdf", [*pages, text_page("End")]), "ign.pdf")],
                                 {"toc.ignore_bookmarks": True})
    assert collect.needs_raster(ignored) and toc_run._gold(ignored) == []


def test_a_root_bookmark_the_knob_drops_does_not_count_as_contents_for_a_raster_read(stand, tmp_path):
    from evaluation import toc_run

    pages = [text_page("Title", bookmark="The book"), {**text_page("Text", bookmark="Only chapter"), "level": 1},
             text_page("More text")]
    kept, _ = intake.register([(build(tmp_path / "kept.pdf", pages), "kept.pdf")])
    assert not collect.needs_raster(kept)
    rootless, _ = intake.register([(build(tmp_path / "root.pdf", [*pages, text_page("End")]), "root.pdf")],
                                  {"toc.skip_root_bookmark": True})
    assert collect.needs_raster(rootless) and [e.title for e in toc_run._gold(rootless)] == ["Only chapter"]


def test_named_contents_pages_that_hold_text_are_read_as_text_not_as_a_picture(stand, tmp_path):
    book_id, _ = intake.register([(build(tmp_path / "named.pdf", [text_page("Title"), contents(),
                                                                  text_page("One")]), "named.pdf")],
                                 {"toc.contents_pages": [[2, 2]]})
    assert not collect.needs_raster(book_id)


def test_a_word_repeated_before_chapter_numbers_is_found_inside_merged_lines_and_a_name_in_the_prose_is_not():
    from stages.toc.sources import labelled

    pages = {p: f"Синдер погледна Кай. Синдер каза нещо. Текст на страница {p}." for p in range(1, 31)}
    pages[2] = "…обуща.\nГлава първа Винтът в глезена на Синдер беше се покрил"
    pages[9] = "линейка дошла. Глава втора Сирените на линейката"
    pages[20] = "трудно. Глава двайсет и първа Синдер тежко се отпусна"
    pages[25] = "Тя нямаше глава за това."
    label, hits = labelled.discover(pages, lambda page, heading: heading.startswith("Глава"))
    assert label == "глава" and hits == [(2, "Глава първа"), (9, "Глава втора"), (20, "Глава двайсет и първа")]


def test_a_heading_is_set_apart_when_its_glyphs_stand_on_their_own_line_centred_and_prose_is_not():
    from stages.toc.sources import labelled

    def run(text, top, x=0.1, height=0.02):
        out = []
        for ch in text:
            if not ch.isspace():
                out.append((x, top, x + 0.01, top + height, ch))
            x += 0.012
        return out

    page = run("обуща.", 0.05) + run("Главапърва", 0.09, x=0.44, height=0.022) + run("Винтътвглезена", 0.13)
    assert labelled.set_apart(page, "Глава първа")
    assert not labelled.set_apart(run("Він вловлював будь який шум", 0.2), "Він вловлював")


def test_a_scanned_contents_set_as_text_blocks_with_bracketed_pages_is_read_and_its_heading_dropped():
    from stages.toc import scan

    def block(kind, text):
        return {"type": kind, "content": [{"type": "text", "content": text}]}

    page = {"blocks": [block("doc_title", "ОЛАВЛЕНИЕ ГЛАВА ПЕРВАЯ"), block("doc_title", "ГЛАВА ПЕРВАЯ,"),
                       block("text", "в которой всё начинается (3)"), block("text", "ГЛАВА ВТОРАЯ,"),
                       block("text", "в которой лазер (46)"), block("paragraph_title", "ГЛАВА ТРЕТЬЯ,"),
                       block("text", "в которой река (98)")]}
    prose = {"blocks": [block("text", "Один абзац (12)"), block("text", "Другой абзац (40)")]}
    found, pages = scan.entries({7: page, 30: prose}, 280)
    assert pages == [7] and [(e.title, e.printed) for e in found] == [
        ("ГЛАВА ПЕРВАЯ, в которой всё начинается", "3"), ("ГЛАВА ВТОРАЯ, в которой лазер", "46"),
        ("ГЛАВА ТРЕТЬЯ, в которой река", "98")]


def _block(kind: str, text: str, size: float, y: float) -> dict:
    # a box whose area gives `size` back through the headings source's size proxy
    width = 0.6
    height = (size / 1000) ** 2 * 0.66 * len(text) / width
    return {"type": kind, "bbox": [0.2, y, 0.2 + width, y + height], "content": text}


def _headed_book(pages: int = 100) -> dict[int, dict]:
    body = " ".join(["word"] * 25)
    layouts = {p: {"blocks": [_block("header", f"The Book {p}", 12, 0.02), _block("text", body, 15, 0.5)]}
               for p in range(1, pages + 1)}
    for n, page in enumerate((5, 22, 39, 56, 73, 90), start=1):
        # the fifth chapter's title is typed as page furniture, as MinerU types a title at a page's top
        kind = "header" if n == 5 else "paragraph_title"
        layouts[page]["blocks"].insert(1, _block(kind, f"Chapter {n} Topic {n}", 30, 0.1))
        layouts[page + 3]["blocks"].insert(1, _block("paragraph_title", f"{n}.1 First look", 20, 0.3))
    return layouts


def test_headings_give_the_chapters_by_their_look_and_leave_the_running_heads_out():
    from stages.toc import scan
    from stages.toc.sources import headings

    got = headings.read(_headed_book(), 100, scan._text)
    assert got.failed is None and got.source == "headings"
    assert [(e.title, e.page) for e in got.entries if e.level == 1] == [
        (f"Chapter {n} Topic {n}", p) for n, p in enumerate((5, 22, 39, 56, 73, 90), start=1)]
    assert [e.page for e in got.entries if e.level == 2] == [8, 25, 42, 59, 76, 93]
    assert not any(e.title.startswith("The Book") for e in got.entries)


def test_a_title_stays_a_heading_when_its_running_heads_repeat_its_name():
    from stages.toc.sources import headings

    bl = [{"page": 3, "type": "paragraph_title", "text": "Introduction", "size": 30, "words": 1}]
    bl += [{"page": p, "type": "header", "text": "Introduction", "size": 12, "words": 1} for p in range(4, 9)]
    _, cand = headings.candidates(bl, 100)
    assert [(b["page"], b["type"]) for b in cand] == [(3, "paragraph_title")]


def test_title_page_lines_before_a_contents_at_the_start_are_no_chapters():
    from stages.toc import scan
    from stages.toc.sources import headings

    layouts = _headed_book()
    for page, text in ((1, "A Series Of Books"), (2, "The Publisher House"), (3, "Contents")):
        layouts[page]["blocks"].insert(1, _block("paragraph_title", text, 30, 0.1))
    kept = headings.read(layouts, 100, scan._text)
    assert {e.page for e in kept.entries} >= {1, 2, 3}
    cut = headings.read(layouts, 100, scan._text, frozenset({3, 4}))
    assert min(e.page for e in cut.entries) == 5
    assert [e.page for e in cut.entries if e.level == 1] == [5, 22, 39, 56, 73, 90]
    # a contents printed at the book's end cuts nothing
    assert headings.read(layouts, 100, scan._text, frozenset({97, 98})).entries == kept.entries


def test_a_long_title_counts_as_a_heading_only_when_typed_as_a_document_title():
    from stages.toc.sources import headings

    long = " ".join(["word"] * 23)
    bl = [{"page": 3, "type": "doc_title", "text": long, "size": 30, "words": 23},
          {"page": 9, "type": "paragraph_title", "text": long, "size": 30, "words": 23}]
    assert [b["page"] for b in headings.candidates(bl, 100)[1]] == [3]


def test_too_few_headings_of_one_look_are_no_chapters():
    from stages.toc import scan
    from stages.toc.sources import headings

    layouts = {p: {"blocks": [_block("paragraph_title", f"Chapter {p} Topic", 30, 0.1)]} for p in (10, 40, 70)}
    got = headings.read(layouts, 100, scan._text)
    assert got.failed and not got.entries


def test_a_book_without_contents_takes_its_headings_before_failing_unless_the_knob_says_no(stand, tmp_path,
                                                                                          monkeypatch):
    from stages.toc import scan

    monkeypatch.setattr(scan, "recognise", lambda book_id, book_pages, cached_only=False: _headed_book())
    book_id, _ = intake.register([(build(tmp_path / "h.pdf", [text_page(f"Page {n}") for n in range(100)]),
                                   "headed.pdf")])
    source, entries, evidence = collect.choose(book_id)
    assert source == "headings" and evidence["headings"]["notes"]["chapters"] == 6
    assert collect.choose(book_id, off=("headings",))[0] == "whole_book"
    off, _ = intake.register([(build(tmp_path / "o.pdf", [text_page(f"Page {n}") for n in range(101)]), "off.pdf")],
                             {"toc.from_headings": False})
    with pytest.raises(Final):
        collect.choose(off)


def test_more_chapters_than_half_the_pages_are_no_structure():
    from stages.toc import scan
    from stages.toc.sources import headings

    layouts = {p: {"blocks": [_block("paragraph_title", f"Topic {p}", 30, 0.1)]} for p in range(1, 21)}
    got = headings.read(layouts, 20, scan._text)
    assert got.failed and "a page" in got.failed and not got.entries


def test_chapters_under_a_contents_bookmark_are_chapters_with_their_levels_kept():
    marks = [Entry("Cover", 1, 1), Entry("Table of contents", 1, 6),
             *[Entry(f"{n}. Topic", 2, 10 * n) for n in range(1, 4)], Entry("Index", 1, 90)]
    got = collect.rows(marks, "bookmarks", 100)
    assert [(r["title"], r["level"], r["kind"]) for r in got] == [
        ("Cover", 1, "chapter"), ("Table of contents", 1, "part"), ("1. Topic", 2, "chapter"),
        ("2. Topic", 2, "chapter"), ("3. Topic", 2, "chapter"), ("Index", 1, "chapter")]
    two = [Entry("Contents", 1, 3), Entry("One", 2, 5), Entry("Two", 2, 9), Entry("Body", 1, 12)]
    assert [r["kind"] for r in collect.rows(two, "bookmarks", 20)] == ["chapter", "section", "section", "chapter"]
