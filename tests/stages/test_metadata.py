import pytest
from stages.metadata import file_metadata, resolve, title_pages
from stages.metadata.candidates import SourceResult


def test_isbn_checksum_and_label_rules():
    text = "ISBN 978-5-4461-4313-9\nISBN 0-13-214301-1\nphone 0119890623\n9781492043089"
    found = title_pages.isbns(text)
    assert found == ["9785446143139", "9781492043089", "0132143011"]
    assert "0119890623" not in found


def test_the_year_is_the_latest_by_the_copyright_sign_and_no_word_fields_are_read():
    found = title_pages.read("Copyright © 2019, 2021 O'Reilly Media\nТом 2\n2nd Edition\nPublished by O'Reilly")
    assert {c.field: c.value for c in found.candidates} == {"year": 2021}


@pytest.mark.parametrize("value", ["single.dvi", "Microsoft Word - sosp067.doc", "myebooks", "book-file",
                                   "Learning Python (for Someone Buyer)", "9780132773577.pdf"])
def test_junk_pdf_metadata_is_ignored(value):
    assert file_metadata.is_junk(value, ["book-file.pdf"])


def test_russian_translation_keeps_its_own_isbn():
    found = title_pages.read("ISBN 978-1633437210 англ.\nISBN 978-5-4461-4313-9")
    resolve._own_isbn(found, ["ru"])
    values = {c.field: c.value for c in found.candidates}
    assert values["isbn"] == "9785446143139" and values["_other_isbn"] == "9781633437210"


def _result(source, covers=(), failed=None, **values):
    r = SourceResult(source, covers=covers, failed=failed)
    for k, v in values.items():
        r.add(k, v, 0.8)
    return r


def test_unknown_field_lists_every_source_tried():
    rows = {r["name"]: r for r in resolve.resolve([
        _result("title_pages", covers=("series", "year"), failed="no title pages"),
        _result("model", covers=("series",)),
    ])}
    series = rows["series"]
    assert series["value"] is None
    assert {a["source"]: a["outcome"] for a in series["attempts"]} == {"title_pages": "failed", "model": "absent"}


def test_rank_and_conflict():
    rows = {r["name"]: r for r in resolve.resolve([
        _result("file_metadata", covers=("title",), title="junkish"),
        _result("title_pages", covers=("title",), title="Kafka"),
        _result("model", covers=("title",), title="Kafka"),
    ])}
    title = rows["title"]
    assert title["value"] == "Kafka" and title["source"] == "title_pages"
    assert {a["source"]: a["outcome"] for a in title["attempts"]}["file_metadata"] == "conflict"
    assert title["confidence"] < 0.8


def test_inline_images_are_dropped_from_recognised_text():
    text = "# ТИТУЛ\n![](data:image/jpeg;base64,/9j/4AAQSkZJRgABAQ)\nИван"
    assert "base64" not in resolve.without_images(text)


def test_language_ignores_noise_tokens():
    from stages.metadata import language

    text = ("Это обычный русский текст книги про контейнеры и микросервисы. " * 20) + " /9j/4AAQSkZJRgABAQAAAQ" * 50
    assert [c.value for c in language.read(text).candidates] == [["ru"]]


def test_a_foreign_isbn_after_the_russian_one_is_not_the_books_own():
    found = title_pages.read("ISBN 978-5-4461-4313-9\nISBN 978-1633437210")
    resolve._own_isbn(found, ["ru"])
    values = {c.field: c.value for c in found.candidates}
    assert values["isbn"] == "9785446143139" and values["_other_isbn"] == "9781633437210"


def test_the_first_isbn_of_an_english_book_stays_its_own():
    found = title_pages.read("ISBN 978-1-492-04308-9\n... other titles ... ISBN 978-1-491-98364-5")
    resolve._own_isbn(found, ["en"])
    assert {c.field: c.value for c in found.candidates}["isbn"] == "9781492043089"


def test_isbn_with_dashes_and_spaces_from_recognition():
    assert title_pages.isbns("ISBN 5—88600—001 — 1") == ["5886000011"]


def test_garbled_layer_is_not_a_layer():
    import pdf

    junk = "!\n, . \xad\n“ “ “\n, , ,\n. . / . . . .— .:\n“ \", - “ \", 1992.—336 .: 130 .\n" * 3
    assert not pdf.has_layer(junk) and pdf.garbled(junk)
    assert pdf.has_layer("Обычный текст страницы с достаточным количеством букв для слоя.")
    shifted = "ɨɛɟɫɱɟɫɬɢɬɶɫɟɛɹ, ɨɩɨɡɨɪɢɬɶɫɹ Ɉɬɫɢɥɶɧɨɝɨɠɚɪɚ ɨɧɫɬɚɥɤɪɚɫɧɵɦ ɤɚɤɦɟɞɧɚɹɦɨɧɟɬɚ"
    assert pdf.has_layer(shifted) and pdf.garbled(shifted)
    assert not pdf.garbled("A dictionary line: cat [kæt] n. a small animal kept as a pet in many homes")


def test_russian_catalogue_card():
    card = ("Я47 Мальчик с коньками: Рассказ/ Рис. Г. Мазурина.— Переизд.— М.: Дет. лит., 1988.— 47 с., ил.— "
            "(Книга за книгой).")
    values = {c.field: c.value for c in title_pages.read(card).candidates}
    assert values["series"] == "Книга за книгой" and "edition" not in values


def test_all_caps_title_reads_as_a_sentence():
    assert resolve.uncapped("МАЛЬЧИК С КОНЬКАМИ") == "Мальчик с коньками"
    assert resolve.uncapped("NGINX") == "NGINX"
    assert resolve.uncapped("Kafka: The Definitive Guide") == "Kafka: The Definitive Guide"


UA_ISBN = "9786177535125"


def test_ukrainian_translation_keeps_its_own_isbn():
    found = title_pages.read(f"ISBN 978-1-492-04308-9\nISBN {UA_ISBN}")
    resolve._own_isbn(found, ["uk"])
    values = {c.field: c.value for c in found.candidates if c.field in ("isbn", "_other_isbn")}
    assert values == {"isbn": UA_ISBN, "_other_isbn": "9781492043089"}


def test_language_detector_knows_ukrainian():
    from stages.metadata import language

    text = "Це звичайний український текст книги про рослини та їхнє вирощування в саду. " * 30
    assert [c.value for c in language.read(text).candidates] == [["uk"]]


def test_a_title_in_another_language_becomes_the_original_title():
    model = _result("model", covers=("title",), title="Їжачок та його щастя")
    pdf_info = _result("file_metadata", covers=("title",), title="Ёжик и его счастье")
    results = [model, pdf_info]
    resolve._title_in_book_language(results, "ru")
    rows = {r["name"]: r for r in resolve.resolve(results)}
    assert rows["title"]["value"] == "Ёжик и его счастье"
    assert rows["original_title"]["value"] == "Їжачок та його щастя"


def test_one_line_shaped_like_an_edition_alone_is_not_a_history():
    found = title_pages.read("© 2017 Springer\nAct 2014: the act as amended")
    assert {c.field: c.value for c in found.candidates}["year"] == 2017


@pytest.mark.parametrize("text,year", [
    ("Copyright © 2022 Gwen Shapira\nSeptember 2017: First Edition\nNovember 2021: Second Edition", 2021),
    ("© 2022\nSeptembre 2017 : Première édition\nNovembre 2021: Deuxième édition", 2021),
    ("© Перевод на русский язык ООО «Прогресс книга», 2025\nАнализ данных. — СПб.: Питер, 2026. — 400 с.", 2026),
    ("Архитектуры данных. — Астана:\n«Спринт Бук», 2026. — 288 с.\n© Перевод ТОО «Спринт Бук», 2025", 2026),
    ("© Издательство «Детская литература», 1992", 1992),
])
def test_the_edition_year_comes_before_the_copyright_year(text, year):
    assert {c.field: c.value for c in title_pages.read(text).candidates}["year"] == year


def test_isbn_keeps_its_x():
    assert title_pages.normalise_isbn("0-8044-2957-x") == "080442957X"


def test_an_away_model_defers_the_subject_instead_of_leaving_it_empty(monkeypatch):
    import job_handlers
    from stages.metadata import model_reader

    def away(*a, **kw):
        raise job_handlers.Deferred("ollama away")

    monkeypatch.setattr(model_reader, "subject", away)
    with pytest.raises(job_handlers.Deferred):
        resolve._subject("A title", "pages", "body")


@pytest.mark.parametrize("value,number", [("Volume 4", "4"), ("Band 11", "11"), ("Том IX", "IX"), ("No. 6", "6"),
                                          ("12", "12"), ("Supplement", "Supplement")])
def test_a_volume_is_its_number_whatever_word_precedes_it(value, number):
    from stages.metadata import model_reader

    assert model_reader.volume_number(value) == number


def test_xmp_names_the_book_when_the_info_dictionary_is_junk(tmp_path):
    import pdf

    packet = ('<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF><rdf:Description><dc:title><rdf:Alt>'
              '<rdf:li xml:lang="x-default">L&apos;art grec</rdf:li></rdf:Alt></dc:title><dc:creator><rdf:Seq>'
              '<rdf:li>Jean-Jacques Maffre</rdf:li></rdf:Seq></dc:creator></rdf:Description></rdf:RDF></x:xmpmeta>')
    path = tmp_path / "x.pdf"
    path.write_bytes(b"%PDF-1.4\n" + packet.encode() + b"\n%%EOF")
    xmp = pdf.xmp(path)
    assert xmp == {"title": "L'art grec", "creators": ["Jean-Jacques Maffre"]}
    found = file_metadata.read([{"Title": "Untitled", "Author": "Microsoft Word"}, {}], ["x.pdf"], [{}, xmp])
    assert {c.field: (c.value, c.evidence) for c in found.candidates} == {
        "title": ("L'art grec", "XMP dc:title"), "authors": (["Jean-Jacques Maffre"], "XMP dc:creator")}


def test_a_title_with_a_dotted_name_is_not_a_file_name():
    assert not file_metadata.is_junk("Learning Node.js", ["book.pdf"])


def test_an_edition_equal_to_the_volume_is_the_series_volume(monkeypatch):
    from stages.metadata import model_reader

    def answer(edition, volume):
        reply = '{"title": "T", "edition": %s, "volume": "%s"}' % (edition, volume)
        monkeypatch.setattr(model_reader.model_steps, "call", lambda *a, **k: reply)
        return {c.field: c.value for c in model_reader.read("x" * 60).candidates}

    assert "edition" not in answer(4, "Volume 4")
    assert answer(2, "Volume 4")["edition"] == "2"


def test_the_tools_that_wrote_the_files_are_kept_once_each():
    abbyy, gs = "ABBYY FineReader PDF", "GPL Ghostscript 9.26"
    found = file_metadata.read([{"Producer": abbyy, "Creator": abbyy}, {"Producer": gs}], ["a.pdf", "b.pdf"])
    assert [c.value for c in found.candidates if c.field == "made_with"] == [[abbyy, gs]]
    assert not [c for c in file_metadata.read([{}], ["a.pdf"]).candidates if c.field == "made_with"]
