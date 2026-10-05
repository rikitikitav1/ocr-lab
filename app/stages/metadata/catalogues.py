# external catalogues by ISBN: Open Library for English editions, Labirint for Russian ones
import html
import os
import re

import httpx
import net

from stages.metadata.candidates import SourceResult
from stages.metadata.title_pages import normalise_isbn, same_isbn

TIMEOUT = 20
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) ocr-lab/0.1"}
YEAR_IN = re.compile(r"(?:19|20)\d{2}")


def _client() -> net.Client:
    return net.Client(timeout=TIMEOUT, headers=HEADERS)


def open_library(isbn: str) -> SourceResult:
    out = SourceResult("catalogue:open_library", covers=("title", "authors", "publisher", "year"))
    try:
        with _client() as c:
            seen = c.get("https://openlibrary.org/api/books",
                          params={"bibkeys": f"ISBN:{isbn}", "format": "json", "jscmd": "data"})
            seen.raise_for_status()
            data = seen.json().get(f"ISBN:{isbn}")
    except httpx.HTTPError as e:
        out.failed = str(e)
        return out
    if not data:
        return out
    title = data.get("title", "")
    if data.get("subtitle"):
        title = f"{title}: {data['subtitle']}"
    out.add("title", title, 0.85, f"Open Library ISBN:{isbn}")
    out.add("authors", [a["name"] for a in data.get("authors", [])], 0.85, f"Open Library ISBN:{isbn}")
    out.add("publisher", ", ".join(p["name"] for p in data.get("publishers", [])), 0.8, f"Open Library ISBN:{isbn}")
    if m := YEAR_IN.search(data.get("publish_date", "")):
        out.add("year", int(m.group(0)), 0.8, f"Open Library publish_date {data.get('publish_date')}")
    return out


LABIRINT_LABELS = ("Автор", "Переводчик", "Издательство", "Серия", "ISBN", "Язык", "Страниц", "Редактор",
                   "Художник", "Тип обложки", "Вес", "Размеры", "Все характеристики", "Жанр", "Возрастные")


def _labirint_fields(page: str, labels: tuple[str, ...] = LABIRINT_LABELS) -> dict[str, list[str]]:
    page = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", page, flags=re.S)
    tokens = [html.unescape(t).strip() for t in re.split(r"<[^>]+>", page)]
    tokens = [t for t in tokens if t and t not in (",", "|")]
    fields: dict[str, list[str]] = {}
    current = None
    for token in tokens:
        label = next((lab for lab in labels if token.startswith(lab)), None)
        if label is not None:
            current = label
            fields.setdefault(label, [])
            continue
        if current is not None and len(fields[current]) < 6:
            fields[current].append(token)
    return fields


# the shop heads a page "Title: Surname1, Surname2"; the names go, the title stays
def labirint_title(title: str, authors: list[str]) -> str:
    names = {w.lower().strip(".,") for a in authors for w in a.split()}
    head, sep, tail = title.rpartition(": ")
    if sep and names and {w.lower().strip(".,") for w in tail.split()} & names:
        return head
    return title


def labirint(isbn: str) -> SourceResult:
    out = SourceResult("catalogue:labirint", covers=("title", "authors", "publisher", "year", "series", "languages",
                                                     "translators"))
    try:
        with _client() as c:
            search = c.get(f"https://www.labirint.ru/search/{isbn}/")
            search.raise_for_status()
            link = re.search(r'href="(/books/\d+/)"', search.text)
            if link is None:
                return out
            page = c.get("https://www.labirint.ru" + link.group(1))
            page.raise_for_status()
    except httpx.HTTPError as e:
        out.failed = str(e)
        return out
    fields = _labirint_fields(page.text)
    found = normalise_isbn(" ".join(fields.get("ISBN", [])[:1]))
    if found and not same_isbn(found, isbn):
        out.failed = f"the first search hit is ISBN {found}, not {isbn}"
        return out
    where = f"Labirint {link.group(1)}"
    authors_seen = list(dict.fromkeys(a for a in fields.get("Автор", [])[:4] if not YEAR_IN.fullmatch(a)))
    if m := re.search(r"<h1[^>]*>(.*?)</h1>", page.text, re.S):
        title = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", m.group(1)))).strip()
        out.add("title", labirint_title(title, authors_seen), 0.85, where)
    authors = list(dict.fromkeys(a for a in fields.get("Автор", [])[:4] if not YEAR_IN.fullmatch(a)))
    out.add("authors", authors, 0.8, where)
    publisher = fields.get("Издательство", [])
    if publisher:
        out.add("publisher", publisher[0], 0.85, where)
        years = [int(t) for t in publisher[1:3] if YEAR_IN.fullmatch(t)]
        if years:
            out.add("year", years[0], 0.85, where)
    out.add("translators", list(dict.fromkeys(fields.get("Переводчик", [])[:4])), 0.8, where)
    if fields.get("Серия"):
        out.add("series", fields["Серия"][0], 0.8, where)
    language = {"Русский": "ru", "Английский": "en", "Украинский": "uk", "Немецкий": "de", "Французский": "fr",
                "Испанский": "es", "Итальянский": "it", "Белорусский": "be", "Казахский": "kk"}.get(
        (fields.get("Язык") or [""])[0])
    if language:
        out.add("languages", [language], 0.7, where)
    return out


def google_books(isbn: str) -> SourceResult:
    out = SourceResult("catalogue:google_books", covers=("title", "authors", "publisher", "year", "languages"))
    key = os.getenv("GOOGLE_BOOKS_API_KEY", "")
    if not key:
        out.failed = "GOOGLE_BOOKS_API_KEY is not set"
        return out
    try:
        with _client() as c:
            seen = c.get("https://www.googleapis.com/books/v1/volumes", params={"q": f"isbn:{isbn}", "key": key})
            seen.raise_for_status()
            items = seen.json().get("items") or []
    except httpx.HTTPError as e:
        out.failed = str(e)
        return out
    if not items:
        return out
    v = items[0]["volumeInfo"]
    where = f"Google Books isbn:{isbn}"
    out.add("title", ": ".join(x for x in (v.get("title"), v.get("subtitle")) if x), 0.8, where)
    out.add("authors", v.get("authors", []), 0.8, where)
    out.add("publisher", v.get("publisher"), 0.75, where)
    if m := YEAR_IN.search(v.get("publishedDate", "")):
        out.add("year", int(m.group(0)), 0.75, where)
    if v.get("language"):
        out.add("languages", [v["language"]], 0.6, where)
    return out


TITLE_MATCH = 90
# OpenLibrary keeps MARC language codes
MARC = {"ru": "rus", "uk": "ukr", "en": "eng", "fr": "fre", "de": "ger", "es": "spa", "it": "ita", "pl": "pol",
        "be": "bel", "kk": "kaz", "pt": "por", "nl": "dut", "cs": "cze"}


def _surnames(authors: list[str] | None) -> set[str]:
    return {w.lower().strip(".,") for a in authors or [] for w in a.split() if len(w.strip(".")) > 2}


def _matches(found_title: str, found_authors: list[str], title: str, authors: list[str] | None) -> bool:
    from rapidfuzz import fuzz

    title_ok = fuzz.token_set_ratio(found_title.lower(), title.lower()) >= TITLE_MATCH
    author_ok = not authors or bool(_surnames(found_authors) & _surnames(authors))
    return title_ok and author_ok


# a book has many editions; a value is taken only when title, author and language point at exactly one
def open_library_by_title(title: str, authors: list[str] | None, language: str | None = None,
                          edition: int | None = None, year: int | None = None) -> SourceResult:
    out = SourceResult("catalogue:open_library_title", covers=("publisher", "year", "isbn"))
    params = {"title": title, "limit": 20,
              "fields": "key,title,author_name,publisher,first_publish_year,isbn,edition_count,language"}
    if authors:
        params["author"] = authors[0]
    if language in MARC:
        params["language"] = MARC[language]
    try:
        with _client() as c:
            seen = c.get("https://openlibrary.org/search.json", params=params)
            seen.raise_for_status()
            docs = seen.json().get("docs", [])
    except httpx.HTTPError as e:
        out.failed = str(e)
        return out
    hits = [d for d in docs if _matches(d.get("title", ""), d.get("author_name", []), title, authors)]
    editions = sum(d.get("edition_count", 1) for d in hits)
    if len(hits) == 1 and editions > 1 and (edition or year):
        return _open_library_edition(hits[0], title, language, edition, year, out)
    if len(hits) != 1 or editions != 1:
        if hits:
            out.failed = f"ambiguous: {len(hits)} works, {editions} editions match the title and author"
        return out
    hit, where = hits[0], f"Open Library by title {title!r}, the only matching edition"
    out.add("publisher", (hit.get("publisher") or [None])[0] if len(hit.get("publisher") or []) == 1 else None,
            0.55, where)
    out.add("year", hit.get("first_publish_year"), 0.55, where)
    if len(hit.get("isbn") or []) <= 2:
        out.add("isbn", next((i for i in hit.get("isbn", []) if len(i) == 13), None), 0.5, where)
    return out


EDITION_WORD = re.compile(r"(\d+)(?:st|nd|rd|th)?\b")


# one work, many editions: the book's own edition number and year pick the edition
def _open_library_edition(work: dict, title: str, language: str | None, edition: int | None, year: int | None,
                          out: SourceResult) -> SourceResult:
    from collections import Counter

    try:
        with _client() as c:
            seen = c.get(f"https://openlibrary.org{work['key']}/editions.json", params={"limit": 100})
            seen.raise_for_status()
            entries = seen.json().get("entries", [])
    except httpx.HTTPError as e:
        out.failed = str(e)
        return out
    def fits(e):
        if year and str(year) not in str(e.get("publish_date", "")):
            return False
        if edition:
            m = EDITION_WORD.search(str(e.get("edition_name", "")))
            if m is None or int(m.group(1)) != edition:
                return False
        langs = [x.get("key", "").rsplit("/", 1)[-1] for x in e.get("languages", [])]
        return not (language in MARC and langs and MARC[language] not in langs)
    picked = [e for e in entries if fits(e) and (e.get("isbn_13") or e.get("isbn_10"))]
    isbns = Counter((e.get("isbn_13") or e.get("isbn_10"))[0] for e in picked)
    if not isbns:
        out.failed = f"no edition of {len(entries)} fits edition {edition} and year {year}"
        return out
    ranked = isbns.most_common()
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        out.failed = f"ambiguous: editions with ISBNs {[i for i, _ in ranked]} fit edition {edition}, year {year}"
        return out
    isbn = ranked[0][0]
    where = (f"Open Library edition of {title!r} fitting edition {edition}, year {year}"
             + (f"; also fitting: {[i for i, _ in ranked[1:]]}" if len(ranked) > 1 else ""))
    entry = next(e for e in picked if isbn in (e.get("isbn_13") or e.get("isbn_10")))
    confidence = 0.6 if len(ranked) == 1 else 0.4
    out.add("isbn", isbn, confidence, where)
    out.add("publisher", (entry.get("publishers") or [None])[0], confidence, where)
    if m := YEAR_IN.search(str(entry.get("publish_date", ""))):
        out.add("year", int(m.group(0)), confidence, where)
    return out


def labirint_by_title(title: str, authors: list[str] | None) -> SourceResult:
    out = SourceResult("catalogue:labirint_title", covers=("publisher", "year", "isbn", "series"))
    query = f"{title} {' '.join(sorted(_surnames(authors)))}".strip()
    try:
        with _client() as c:
            search = c.get(f"https://www.labirint.ru/search/{query}/")
            search.raise_for_status()
            links = list(dict.fromkeys(re.findall(r'href="(/books/\d+/)"', search.text)))[:8]
            pages = [(link, c.get("https://www.labirint.ru" + link).text) for link in links]
    except httpx.HTTPError as e:
        out.failed = str(e)
        return out
    hits = []
    for link, page in pages:
        fields = _labirint_fields(page)
        h1 = re.search(r"<h1[^>]*>(.*?)</h1>", page, re.S)
        found = labirint_title(re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", h1.group(1)))).strip()
                               if h1 else "", fields.get("Автор", []))
        if _matches(found, fields.get("Автор", []), title, authors):
            hits.append((link, fields))
    if len(hits) != 1:
        if hits:
            out.failed = f"ambiguous: {len(hits)} editions match the title and author"
        return out
    link, fields = hits[0]
    where = f"Labirint by title {title!r}, the only matching edition {link}"
    publisher = fields.get("Издательство", [])
    if publisher:
        out.add("publisher", publisher[0], 0.55, where)
        years = [int(t) for t in publisher[1:3] if YEAR_IN.fullmatch(t)]
        if years:
            out.add("year", years[0], 0.55, where)
    isbn = normalise_isbn(" ".join(fields.get("ISBN", [])[:1]))
    if len(isbn) in (10, 13):
        out.add("isbn", isbn, 0.5, where)
    if fields.get("Серия"):
        out.add("series", fields["Серия"][0], 0.5, where)
    return out


BOOKVOED_LABELS = ("Автор", "ISBN", "Издательство", "Серия", "Страниц", "Год, тираж", "Переплет", "Раздел",
                   "Перейти к характеристикам", "Переводчик", "Художник", "Возрастное", "Формат", "Вес")


def _bookvoed_page(link: str, where: str) -> SourceResult:
    out = SourceResult("catalogue:bookvoed", covers=("title", "authors", "publisher", "year", "series", "translators"))
    with _client() as c:
        page = c.get("https://www.bookvoed.ru" + link)
        page.raise_for_status()
    fields = _labirint_fields(page.text, BOOKVOED_LABELS)
    if m := re.search(r"<h1[^>]*>(.*?)</h1>", page.text, re.S):
        out.add("title", re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", m.group(1)))).strip(), 0.8, where)
    out.add("authors", [a.strip(" ,") for a in fields.get("Автор", [])[:5] if a.strip(" ,")], 0.75, where)
    out.add("publisher", (fields.get("Издательство") or [None])[0], 0.8, where)
    years = [int(t) for t in fields.get("Год, тираж", [])[:2] if YEAR_IN.fullmatch(t)]
    if years:
        out.add("year", years[0], 0.8, where)
    out.add("series", (fields.get("Серия") or [None])[0], 0.75, where)
    out.add("translators", [a.strip(" ,") for a in fields.get("Переводчик", [])[:4] if a.strip(" ,")], 0.75, where)
    out.add("_isbn", normalise_isbn((fields.get("ISBN") or [""])[0]), 0.8, where)
    return out


def bookvoed(isbn: str) -> SourceResult:
    try:
        with _client() as c:
            search = c.get("https://www.bookvoed.ru/search", params={"q": isbn})
            search.raise_for_status()
        link = re.search(r'href="(/product/[^"?#]+)"', search.text)
        if link is None:
            return SourceResult("catalogue:bookvoed", covers=COVERS["catalogue:bookvoed"])
        out = _bookvoed_page(link.group(1), f"Bookvoed {link.group(1)}")
    except httpx.HTTPError as e:
        return SourceResult("catalogue:bookvoed", covers=COVERS["catalogue:bookvoed"], failed=str(e))
    found = next((c.value for c in out.candidates if c.field == "_isbn"), "")
    if found and not same_isbn(found, isbn):
        return SourceResult("catalogue:bookvoed", covers=COVERS["catalogue:bookvoed"],
                            failed=f"the first search hit is ISBN {found}, not {isbn}")
    return out


def bookvoed_by_title(title: str, authors: list[str] | None) -> SourceResult:
    out = SourceResult("catalogue:bookvoed_title", covers=("publisher", "year", "isbn", "series"))
    query = f"{title} {' '.join(sorted(_surnames(authors)))}".strip()
    try:
        with _client() as c:
            search = c.get("https://www.bookvoed.ru/search", params={"q": query})
            search.raise_for_status()
        links = list(dict.fromkeys(re.findall(r'href="(/product/[^"?#]+)"', search.text)))[:8]
        pages = [_bookvoed_page(link, f"Bookvoed by title {title!r}, {link}") for link in links]
    except httpx.HTTPError as e:
        out.failed = str(e)
        return out
    def value(page, name):
        return next((c.value for c in page.candidates if c.field == name), None)
    hits = [p for p in pages if _matches(value(p, "title") or "", value(p, "authors") or [], title, authors)]
    if len(hits) != 1:
        if hits:
            out.failed = f"ambiguous: {len(hits)} editions match the title and author"
        return out
    hit = hits[0]
    where = next(c.evidence for c in hit.candidates) + ", the only matching edition"
    for name, field in (("publisher", "publisher"), ("year", "year"), ("series", "series"), ("_isbn", "isbn")):
        out.add(field, value(hit, name), 0.55, where)
    return out


# a product page by ISBN-10 answers a plain request (search does not); one call at a time, spaced out
_AMAZON_GAP = 3.0
_amazon_last = [0.0]


def amazon(isbn10: str) -> SourceResult:
    import time

    out = SourceResult("catalogue:amazon", covers=("title", "publisher", "year", "edition"))
    wait = _amazon_last[0] + _AMAZON_GAP - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _amazon_last[0] = time.monotonic()
    try:
        with _client() as c:
            page = c.get(f"https://www.amazon.com/dp/{isbn10}", headers={"Accept-Language": "en-US,en;q=0.9"})
            page.raise_for_status()
    except httpx.HTTPError as e:
        out.failed = str(e)
        return out
    text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"<(script|style)[^>]*>.*?</\1>", " ",
                                                                            page.text, flags=re.S))))
    where = f"Amazon /dp/{isbn10}"
    if m := re.search(r'id="productTitle"[^>]*>([^<]+)<', page.text):
        out.add("title", html.unescape(m.group(1)).strip(), 0.6, where)
    if m := re.search(r"ISBN-13\s+(97[89][-\d]{11,14})", text):
        out.add("_isbn13", normalise_isbn(m.group(1)), 0.8, where)
    if m := re.search(r"Publisher\s+(.{2,60}?)\s+Publication date", text):
        out.add("publisher", m.group(1).strip(), 0.75, where)
    if m := re.search(r"Publication date\s+\w+ \d{1,2}, ((?:19|20)\d{2})", text):
        out.add("year", int(m.group(1)), 0.75, where)
    if m := re.search(r"Edition\s+(\d+)(?:st|nd|rd|th)\b", text):
        out.add("edition", m.group(1), 0.7, where)
    return out


LOOKUPS = {"catalogue:open_library": open_library, "catalogue:labirint": labirint,
           "catalogue:bookvoed": bookvoed, "catalogue:google_books": google_books}
COVERS = {"catalogue:open_library": ("title", "authors", "publisher", "year"),
          "catalogue:labirint": ("title", "authors", "publisher", "year", "series", "languages", "translators"),
          "catalogue:bookvoed": ("title", "authors", "publisher", "year", "series", "translators"),
          "catalogue:google_books": ("title", "authors", "publisher", "year", "languages")}
