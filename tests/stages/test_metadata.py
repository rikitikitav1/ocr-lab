import pytest
from stages.metadata import file_metadata, resolve, title_pages
from stages.metadata.candidates import SourceResult


def test_isbn_checksum_and_label_rules():
    text = "ISBN 978-5-4461-4313-9\nISBN 0-13-214301-1\nphone 0119890623\n9781492043089"
    found = [i for i, _ in title_pages.isbns(text)]
    assert found == ["9785446143139", "9781492043089", "0132143011"]
    assert "0119890623" not in found


@pytest.mark.parametrize("text,edition", [("Second Edition", "2"), ("3rd edition", "3"), ("2-е издание", "2"),
                                          ("Document version 3.2.2", "3.2.2")])
def test_edition_patterns(text, edition):
    assert [c.value for c in title_pages.read(text).candidates if c.field == "edition"] == [edition]


def test_year_series_volume_patterns():
    found = title_pages.read("Copyright © 2019, 2021 O'Reilly Media\nТом 2")
    values = {c.field: c.value for c in found.candidates}
    assert values["year"] == 2021 and values["volume"] == "2"


@pytest.mark.parametrize("value", ["single.dvi", "Microsoft Word - sosp067.doc", "myebooks", "book-file",
                                   "Learning Python (for Someone Buyer)"])
def test_junk_pdf_metadata_is_ignored(value):
    assert file_metadata.is_junk(value, ["book-file.pdf"])


def test_russian_translation_keeps_its_own_isbn():
    found = title_pages.read("ISBN 978-1633437210 англ.\nISBN 978-5-4461-4313-9")
    resolve._own_isbn(found, ["ru"])
    values = {c.field: c.value for c in found.candidates}
    assert values["isbn"] == "9785446143139" and values["original_isbn"] == "9781633437210"


def _result(source, covers=(), failed=None, **values):
    r = SourceResult(source, covers=covers, failed=failed)
    for k, v in values.items():
        r.add(k, v, 0.8)
    return r


def test_unknown_field_lists_every_source_tried():
    rows = {r["name"]: r for r in resolve.resolve([
        _result("title_pages", covers=("isbn", "year")),
        _result("catalogue:labirint", covers=("series",), failed="no ISBN to look up"),
        _result("model", covers=("series",)),
    ])}
    series = rows["series"]
    assert series["value"] is None
    assert {a["source"]: a["outcome"] for a in series["attempts"]} == {"catalogue:labirint": "failed",
                                                                       "model": "absent"}


def test_rank_and_conflict():
    rows = {r["name"]: r for r in resolve.resolve([
        _result("file_metadata", covers=("title",), title="junkish"),
        _result("catalogue:open_library", covers=("title",), title="Kafka"),
        _result("model", covers=("title",), title="Kafka"),
    ])}
    title = rows["title"]
    assert title["value"] == "Kafka" and title["source"] == "catalogue:open_library"
    assert {a["source"]: a["outcome"] for a in title["attempts"]}["file_metadata"] == "conflict"
    assert title["confidence"] < 0.8


def test_inline_images_are_dropped_from_recognised_text():
    text = "# ТИТУЛ\n![](data:image/jpeg;base64,/9j/4AAQSkZJRgABAQ)\nИван"
    assert "base64" not in resolve.without_images(text)


def test_labirint_title_loses_the_author_suffix():
    from stages.metadata import catalogues

    assert catalogues.labirint_title("Анализ данных: Гуджа, Сивяк", ["Гуджа Артур"]) == "Анализ данных"
    assert catalogues.labirint_title("Python: краткий курс", ["Мэтиз Эрик"]) == "Python: краткий курс"
    assert catalogues.labirint_title("Архитектуры данных: Джеймс Серра", ["Серра Джеймс"]) == "Архитектуры данных"


def test_language_ignores_noise_tokens():
    from stages.metadata import language

    text = ("Это обычный русский текст книги про контейнеры и микросервисы. " * 20) + " /9j/4AAQSkZJRgABAQAAAQ" * 50
    assert [c.value for c in language.read(text).candidates] == [["ru"]]


def test_foreign_isbn_after_the_russian_one_is_the_original():
    found = title_pages.read("ISBN 978-5-4461-4313-9\nISBN 978-1633437210")
    resolve._own_isbn(found, ["ru"])
    values = {c.field: c.value for c in found.candidates}
    assert values["isbn"] == "9785446143139" and values["original_isbn"] == "9781633437210"


def test_later_isbn_in_an_english_book_is_not_an_original():
    found = title_pages.read("ISBN 978-1-492-04308-9\n... other titles ... ISBN 978-1-491-98364-5")
    resolve._own_isbn(found, ["en"])
    assert "original_isbn" not in {c.field for c in found.candidates}


def test_translation_credits():
    ru = title_pages.read("Перевод с английского и комментарии:© 1989–1992 Беспалова\nЛара Беспалова, 2001 г.")
    assert [c.value for c in ru.candidates if c.field == "translators"] == [["Беспалова"]]
    en = title_pages.read("Translated from Russian by Richard Pevear and Larissa Volokhonsky")
    assert [c.value for c in en.candidates if c.field == "translators"] == [["Richard Pevear"]]


def test_original_title_and_year():
    found = title_pages.read("Оригинальное название: Animal Farm\nOriginally published in 1945 by Secker")
    values = {c.field: c.value for c in found.candidates}
    assert values["original_title"] == "Animal Farm" and values["original_year"] == 1945


def test_isbn_with_dashes_and_spaces_from_recognition():
    assert [i for i, _ in title_pages.isbns("ISBN 5—88600—001 — 1")] == ["5886000011"]


def test_romanised_catalogue_value_loses_to_cyrillic():
    rows = {r["name"]: r for r in resolve.resolve([
        _result("catalogue:open_library", covers=("title",), title="Mir rasteniĭ"),
        _result("model", covers=("title",), title="Мир растений"),
    ], book_script="CYRILLIC")}
    assert rows["title"]["value"] == "Мир растений"


def test_garbled_layer_is_not_a_layer():
    import pdf

    junk = "!\n, . \xad\n“ “ “\n, , ,\n. . / . . . .— .:\n“ \", - “ \", 1992.—336 .: 130 .\n" * 3
    assert not pdf.has_layer(junk) and pdf.garbled(junk)
    assert pdf.has_layer("Обычный текст страницы с достаточным количеством букв для слоя.")


def test_russian_catalogue_card():
    card = ("Я47 Мальчик с коньками: Рассказ/ Рис. Г. Мазурина.— Переизд.— М.: Дет. лит., 1988.— 47 с., ил.— "
            "(Книга за книгой).")
    values = {c.field: c.value for c in title_pages.read(card).candidates}
    assert values["series"] == "Книга за книгой"
    assert values["illustrators"] == ["Г. Мазурина"]
    assert values["edition"] == "reissue"


def test_all_caps_title_reads_as_a_sentence():
    assert resolve.uncapped("МАЛЬЧИК С КОНЬКАМИ") == "Мальчик с коньками"
    assert resolve.uncapped("NGINX") == "NGINX"
    assert resolve.uncapped("Kafka: The Definitive Guide") == "Kafka: The Definitive Guide"


UA_ISBN = "9786177535125"


def test_ukrainian_translation_keeps_its_own_isbn():
    found = title_pages.read(f"ISBN 978-1-492-04308-9\nISBN {UA_ISBN}")
    resolve._own_isbn(found, ["uk"])
    values = {c.field: c.value for c in found.candidates if c.field in ("isbn", "original_isbn")}
    assert values == {"isbn": UA_ISBN, "original_isbn": "9781492043089"}


def test_book_script_beats_romanised_records_in_any_script():
    rows = {r["name"]: r for r in resolve.resolve([
        _result("catalogue:open_library", covers=("title",), title="Svit roslyn"),
        _result("model", covers=("title",), title="Світ рослин"),
    ], book_script="CYRILLIC")}
    assert rows["title"]["value"] == "Світ рослин"
    greek = {r["name"]: r for r in resolve.resolve([
        _result("catalogue:open_library", covers=("title",), title="Odysseia"),
        _result("model", covers=("title",), title="Οδύσσεια"),
    ], book_script="GREEK")}
    assert greek["title"]["value"] == "Οδύσσεια"


@pytest.mark.parametrize("text,edition", [("3. Auflage", "3"), ("2e édition", "2"), ("2-ге видання", "2"),
                                          ("wydanie 4", "4")])
def test_edition_patterns_beyond_russian_and_english(text, edition):
    assert [c.value for c in title_pages.read(text).candidates if c.field == "edition"] == [edition]


@pytest.mark.parametrize("text,name", [("Переклад з англійської: Олена Петренко", "Олена Петренко"),
                                       ("Übersetzt von Hans Wolf", "Hans Wolf"),
                                       ("Traduit de l'anglais par Marie Durand", "Marie Durand")])
def test_translators_beyond_russian_and_english(text, name):
    assert [c.value for c in title_pages.read(text).candidates if c.field == "translators"] == [[name]]


def test_language_detector_knows_ukrainian():
    from stages.metadata import language

    text = "Це звичайний український текст книги про рослини та їхнє вирощування в саду. " * 30
    assert [c.value for c in language.read(text).candidates] == [["uk"]]


def test_ukrainian_translated_by_verb():
    found = title_pages.read("З англійської переклав В’ячеслав Стельмах\nсерія класика")
    assert [c.value for c in found.candidates if c.field == "translators"] == [["В’ячеслав Стельмах"]]


def test_original_title_needs_an_explicit_label():
    assert not [c for c in title_pages.read("un style original de la Grèce").candidates
                if c.field == "original_title"]
    found = title_pages.read("Titre original : The Greek Art")
    assert [c.value for c in found.candidates if c.field == "original_title"] == ["The Greek Art"]


def test_shop_link_isbn_is_a_lookup_key_not_the_books_own():
    found = title_pages.read("A paper version is printed by No Starch Press at http://a-fwd.com/com=x&asin-com=1593279507.")
    values = {c.field: c.value for c in found.candidates}
    assert values["_link_isbn"] == "1593279507" and "isbn" not in values
    assert values["publisher"] == "No Starch Press"


@pytest.mark.parametrize("text,publisher", [("Издательство «Питер», 2026", "Питер"),
                                            ("Published by O'Reilly Media, Inc.", "O'Reilly Media"),
                                            ("Видавництво «Ранок»\n", "Ранок")])
def test_publisher_phrases(text, publisher):
    assert [c.value for c in title_pages.read(text).candidates if c.field == "publisher"] == [publisher]


def test_isbn10_from_isbn13():
    assert title_pages.isbn10_of("9781593279509") == "1593279507"
    assert title_pages.isbn10_of("9791234567896") is None


@pytest.mark.parametrize("text", ["издательство просит присылать по адресу:",
                                  "published by the default exception handling routines"])
def test_publisher_phrase_ignores_prose(text):
    assert not [c for c in title_pages.read(text).candidates if c.field == "publisher"]


def test_publisher_in_quotes_across_a_line_break():
    found = title_pages.read("Издательство «Молодая\nгвардия», 1988")
    assert [c.value for c in found.candidates if c.field == "publisher"] == ["Молодая гвардия"]


def test_imprint_names_the_platform_and_the_version_year():
    found = title_pages.imprint("Эта книга предназначена для продажи на http://leanpub.com/cloud-native-docker-k8s\n"
                                "Эта версия была опубликована 2024-01-24\nЭто книга с Leanpub book.")
    values = {c.field: c.value for c in found.candidates}
    assert values == {"publisher": "Leanpub", "year": 2024}


def test_book_card_from_json_ld():
    from stages.metadata import web

    page = ('<script type="application/ld+json">{"@type": "Book", "name": "Программирование Cloud Native",'
            ' "isbn": "9785449833877", "author": {"@type": "Thing", "name": "Иван Портянкин"},'
            ' "publisher": {"name": "Издательские решения"}, "datePublished": "2022-06-30", "numberOfPages": 192}'
            '</script>')
    card = web.card_from("https://mybook.ru/x", page)[0]
    assert (card["isbn"], card["publisher"], card["year"], card["pages"]) == ("9785449833877", "Издательские решения",
                                                                                2022, 192)


def test_links_in_text_skip_social_sites():
    from stages.metadata import web

    text = "сайт www.ipsoftware.ru, код на https://github.com/ivanporty/x и http://leanpub.com/book."
    assert web.links_in(text) == ["https://www.ipsoftware.ru", "http://leanpub.com/book"]


def test_a_latin_name_on_a_cyrillic_book_is_not_a_romanisation():
    rows = {r["name"]: r for r in resolve.resolve([
        _result("imprint", covers=("publisher",), publisher="Leanpub"),
        _result("web", covers=("publisher",), publisher="Издательские решения"),
    ], book_script="CYRILLIC")}
    assert rows["publisher"]["value"] == "Leanpub"


def test_a_shop_in_the_publisher_field_is_dropped():
    from stages.metadata import web

    page = '<script type="application/ld+json">{"@type": "Book", "name": "X", "publisher": {"name": "ЛитРес"}}</script>'
    assert web.card_from("https://www.litres.ru/x", page)[0]["publisher"] is None


def test_a_title_in_another_language_becomes_the_original_title():
    model = _result("model", covers=("title",), title="Їжачок та його щастя")
    pdf_info = _result("file_metadata", covers=("title",), title="Ёжик и его счастье")
    results = [model, pdf_info]
    resolve._title_in_book_language(results, "ru")
    rows = {r["name"]: r for r in resolve.resolve(results)}
    assert rows["title"]["value"] == "Ёжик и его счастье"
    assert rows["original_title"]["value"] == "Їжачок та його щастя"
