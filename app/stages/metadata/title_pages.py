# patterns over the title and copyright pages: ISBN with its checksum, year, edition, volume
import re

from stages.metadata.candidates import SourceResult

# recognised pages print the hyphens as en or em dashes, often with spaces around them
SEP = r"[-–—\s]{0,3}"
ISBN13 = re.compile(rf"(97[89]{SEP}(?:\d{SEP}){{9}}\d)")
ISBN10_LABELLED = re.compile(rf"ISBN(?:-10)?[:\s]*((?:\d{SEP}){{9}}[\dXx])")
COPYRIGHT_LINE = re.compile(r"(?:©|\(c\)|copyright)[^\n]{0,120}", re.IGNORECASE)
YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
EDITION_EN = re.compile(r"\b(First|Second|Third|Fourth|Fifth|Sixth|Seventh|Eighth|\d+(?:st|nd|rd|th))\s+Edition",
                        re.IGNORECASE)
# "3-е издание", "2-ге видання", "3. Auflage", "2e édition", "2.ª edición", "wydanie 2": the number
EDITION_ANY = re.compile(r"(\d+)\s?[-.]?\s?(?:е|ге|тє|ье|e|ème|ª|a)?\s+"
                         r"(?:издание|видання|Auflage|[ée]dition|edici[óo]n|edizione|edição|uitgave|vydání)"
                         r"|(?:wydanie|издание|видання)\s+(\d+)", re.IGNORECASE)
VOLUME = re.compile(r"(?<![^\W\d_])(?:Том|Т\.|Volume|Vol\.|Band|Bd\.|Tome|Tomo|Tom|Svazek)\s*(\d+|[IVX]+)\b",
                    re.IGNORECASE)
ORIGINAL_HINT = re.compile(r"original|оригинал|англ|English", re.IGNORECASE)
# translation credits beyond Russian and English: Ukrainian, German, French, Spanish, Italian, Polish, Portuguese
TRANSLATED_OTHER = re.compile(r"(?:[Пп]ереклад(?:\s+з\s+[^\W\d_]+)?|(?:[Зз]\s+[^\W\d_]+\s+)?переклал?[аи]?в?|"
                              r"[Üü]bersetzt von|"
                              r"[Üü]bersetzung(?: aus dem \w+)?:?|[Tt]raduit (?:de l'\w+ )?par|"
                              r"[Tt]raducci[óo]n(?: de)?:?|[Tt]radotto da|[Tt]raduzione di|"
                              r"[Pp]rzełożył[a]?|[Tt]łumaczenie:?|[Tt]radução(?: de)?:?)\s*[:—-]?\s*"
                              r"([^\W\d_](?:[^\W\d_]|[’'])*\.?(?:[ \t]+[^\W\d_](?:[^\W\d_]|[’'])*\.?){0,2})")
TRANSLATED_RU = re.compile(r"[Пп]еревод(?:\s+с\s+[а-яё]+(?:ого|кого)?)?(?:\s+и\s+[а-яё ]+?)?\s*[:—-]\s*"
                           r"(?:©\s*[\d–-]*\s*)?"
                           r"([А-ЯЁ][а-яё]+(?:[ \t]+[А-ЯЁ]\.[ \t]*[А-ЯЁ]?\.?|[ \t]+[А-ЯЁ][а-яё]+)?)")
TRANSLATED_EN = re.compile(r"[Tt]ranslated (?:from [A-Z][a-z]+ )?by "
                           r"([A-Z][a-z]+(?:[ \t]+[A-Z]\.)?(?:[ \t]+[A-Z][a-z]+)+)")
# only an explicit label: a bare "original" matched French prose ("original de")
ORIGINAL_TITLE = re.compile(r"(?:[Оо]ригинальное название|[Нн]азвание оригинала|[Нн]азва оригіналу|[Oo]riginal title|"
                            r"[Tt]itre original|[Oo]riginaltitel|[Tt]ítulo original|[Tt]itolo originale|"
                            r"[Oo]riginally published (?:in \w+ )?(?:as|under the title))\s*[:—-]?\s*"
                            r"[«\"“]?([^\W\d_][^\n«»\"”]{2,80})")
ORIGINAL_YEAR = re.compile(r"(?:[Оо]ригинал|[Oo]riginal(?:ly)?|first published)[^\n]{0,60}?\b((?:1[5-9]|20)\d{2})\b")
# the Russian catalogue card on the imprint page: "Title: Kind / Рис. Г. Мазурина.— Переизд.— М.: Дет. лит.,
# 1988.— 47 с., ил.— (Книга за книгой)."
CARD = re.compile(r"[^\n]*?\.\s?[—-]\s?[^\W\d_][^\W\d_]*\.?(?:\s?[^\W\d_]+\.?)?\s?:\s?"
                  r"[^\n]+?,\s?((?:19|20)\d{2})[^\n]*")
CARD_SERIES = re.compile(r"[—-]\s?\(([^()]{3,80})\)\.?\s*$")
ILLUSTRATED_BY = re.compile(r"(?:Рис\.|Худож(?:ник)?\.?|Ілюстр(?:ації|ував)?\.?|Художник:|[Ii]llustrated by|"
                            r"[Ii]llustrations by|[Ii]llustriert von|[Ii]llustrations de|[Ii]lustraciones de)\s*"
                            r"([А-ЯЁA-Z]\.\s?(?:[А-ЯЁA-Z]\.\s?)?[А-ЯЁA-Z][а-яёa-z]+"
                            r"|[А-ЯЁA-Z][а-яёa-z]+(?:\s[А-ЯЁA-Z][а-яёa-z]+)?)")
REISSUE = re.compile(r"[Пп]ереизд\.?|[Пп]ереиздание|[Пп]еревидання|[Nn]euauflage|[Rr]éédition|[Rr]eimpresi[óo]n")
# a shop link printed in the book carries an ISBN-10 as its ASIN; it may point at another edition, so it is a
# lookup key, never the book's own ISBN by itself
LINK_ISBN = re.compile(r"(?:asin(?:-com)?=|/dp/|/gp/product/|isbn=)(\d{9}[\dX])", re.IGNORECASE)
# the name is quoted (quotes may wrap a line) or starts with a capital: "издательство просит присылать" and
# "published by the default handler" are prose, not publishers
PUBLISHED_BY = re.compile(r"(?:[Pp]ublished by|[Pp]rinted by|[Pp]ublisher:|[Ии]здательство|[Вв]идавництво|[Vv]erlag:|"
                          r"[ÉéEe]ditions|[Ee]ditorial)\s*:?\s*(?:[«\"“]([^«»\"”]{2,60})[»\"”]"
                          r"|([A-ZА-ЯЁІЇЄҐ][^\n,;«»\"”]{1,60}?)(?:\s+(?:at|in|в)\s|[,;.\n]|$))")
# the file says what it is: a self-publishing platform's edition, or the date of this version
PLATFORMS = {"leanpub": "Leanpub", "ridero": "Ridero", "lulu.com": "Lulu", "createspace": "CreateSpace",
             "smashwords": "Smashwords", "литрес: самиздат": "ЛитРес: Самиздат", "издательские решения":
             "Издательские решения", "kindle direct publishing": "Kindle Direct Publishing"}
PLATFORM_CLAIM = re.compile(r"(?:книга с|is a|this is a|published (?:on|with|via|through)|для продажи на|"
                            r"available (?:on|at)|sold on)\s+(?:https?://)?(?:www\.)?([\w.:\- ]{3,40})", re.IGNORECASE)
VERSION_YEAR = re.compile(r"(?:[Ээ]та версия (?:была )?опубликована|[Tt]his version was published(?: on)?|"
                          r"[Цц]я версія (?:була )?опублікована)\s*:?\s*((?:19|20)\d{2})")
# manuals carry a document version instead of an edition number
DOC_VERSION = re.compile(r"(?:[Dd]ocument version|[Dd]ocumentation version|[Вв]ерсия документа)\s*:?\s*"
                         r"(\d+(?:\.\d+){1,3})")
ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8}


def isbn_valid(raw: str) -> bool:
    digits = re.sub(r"[-–—\s]", "", raw).upper()
    if len(digits) == 13 and digits.isdigit():
        return sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(digits)) % 10 == 0
    if len(digits) == 10 and digits[:9].isdigit() and (digits[9].isdigit() or digits[9] == "X"):
        return sum((10 - i) * (10 if c == "X" else int(c)) for i, c in enumerate(digits)) % 11 == 0
    return False


def isbn10_of(isbn13: str) -> str | None:
    if len(isbn13) != 13 or not isbn13.startswith("978"):
        return None
    core = isbn13[3:12]
    check = (11 - sum((10 - i) * int(c) for i, c in enumerate(core)) % 11) % 11
    return core + ("X" if check == 10 else str(check))


# the one way to read an ISBN anywhere: digits and a final X, nothing else
def normalise_isbn(raw) -> str:
    return re.sub(r"[^\dX]", "", str(raw or "").upper())


def isbn13_of(isbn: str) -> str | None:
    isbn = normalise_isbn(isbn)
    if len(isbn) == 13:
        return isbn
    if len(isbn) != 10:
        return None
    core = "978" + isbn[:9]
    check = (10 - sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(core)) % 10) % 10
    return core + str(check)


# the same book whether written as ISBN-10 or ISBN-13, with or without hyphens
def same_isbn(a, b) -> bool:
    return bool(a) and bool(b) and isbn13_of(str(a)) is not None and isbn13_of(str(a)) == isbn13_of(str(b))


def isbns(text: str) -> list[tuple[str, str]]:
    found = []
    for pattern in (ISBN13, ISBN10_LABELLED):
        for m in pattern.finditer(text):
            if isbn_valid(m.group(1)):
                context = text[max(0, m.start() - 120):m.start()]
                found.append((normalise_isbn(m.group(1)), context))
    seen, out = set(), []
    for isbn, context in found:
        if isbn not in seen:
            seen.add(isbn)
            out.append((isbn, context))
    return out


def imprint(text: str) -> SourceResult:
    out = SourceResult("imprint", covers=("publisher", "year"))
    for m in PLATFORM_CLAIM.finditer(text):
        named = next((v for k, v in PLATFORMS.items() if k in m.group(1).lower()), None)
        if named:
            out.add("publisher", named, 0.7, f"the file names its platform: {m.group(0)[:100]}")
            break
    if m := VERSION_YEAR.search(text):
        out.add("year", int(m.group(1)), 0.75, f"the file dates this version: {m.group(0)[:100]}")
    return out


def read(text: str) -> SourceResult:
    out = SourceResult("title_pages", covers=("isbn", "original_isbn", "year", "edition", "volume", "translators",
                                              "illustrators", "series", "original_title", "original_year", "publisher"))
    found = isbns(text)
    originals = [i for i, ctx in found if ORIGINAL_HINT.search(ctx)]
    own = [i for i, _ in found if i not in originals]
    if own:
        out.add("isbn", own[0], 0.8, f"first ISBN in the title pages; all found: {[i for i, _ in found]}")
    # later ones are often other books advertised in the front matter; kept only for the translation rule
    for other in own[1:]:
        out.add("_other_isbn", other, 0.2, "a later ISBN in the title pages")
    if originals:
        out.add("original_isbn", originals[0], 0.6, "ISBN next to an original-edition note")
    for link in dict.fromkeys(m.group(1).upper() for m in LINK_ISBN.finditer(text)):
        if isbn_valid(link):
            out.add("_link_isbn", link, 0.3, "an ISBN-10 inside a shop link in the book")
    if m := PUBLISHED_BY.search(text):
        out.add("publisher", re.sub(r"\s+", " ", m.group(1) or m.group(2)).strip(), 0.5, m.group(0)[:120])
    years = [int(y) for line in COPYRIGHT_LINE.findall(text) for y in YEAR.findall(line)]
    if years:
        out.add("year", max(years), 0.6, "latest copyright year")
    if m := EDITION_EN.search(text):
        word = m.group(1).lower()
        out.add("edition", str(ORDINALS.get(word) or int(re.sub(r"\D", "", word))), 0.7, m.group(0))
    elif m := EDITION_ANY.search(text):
        out.add("edition", str(int(m.group(1) or m.group(2))), 0.7, m.group(0))
    elif m := DOC_VERSION.search(text):
        out.add("edition", m.group(1), 0.6, m.group(0))
    if m := VOLUME.search(text):
        out.add("volume", m.group(1), 0.5, m.group(0))
    for m in CARD.finditer(text):
        card = m.group(0)
        if s := CARD_SERIES.search(card):
            out.add("series", s.group(1).strip(), 0.7, f"catalogue card: {card[:160]}")
        if REISSUE.search(card):
            out.add("edition", "reissue", 0.5, f"catalogue card: {card[:160]}")
        break
    illustrators = list(dict.fromkeys(m.group(1).strip() for m in ILLUSTRATED_BY.finditer(text)))
    if illustrators:
        out.add("illustrators", illustrators, 0.6, "an illustration credit in the title pages")
    translators = list(dict.fromkeys(m.group(1).strip() for p in (TRANSLATED_RU, TRANSLATED_EN, TRANSLATED_OTHER)
                                     for m in p.finditer(text)))
    if translators:
        out.add("translators", translators, 0.6, "a translation credit in the title pages")
    if m := ORIGINAL_TITLE.search(text):
        out.add("original_title", m.group(1).strip(" .,"), 0.6, m.group(0)[:120])
    if m := ORIGINAL_YEAR.search(text):
        out.add("original_year", int(m.group(1)), 0.5, m.group(0)[:120])
    return out
