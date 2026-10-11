# patterns over the title and copyright pages, read by signs and shapes rather than words of a language
import re

from stages.metadata.candidates import SourceResult

# recognised pages print the hyphens as en or em dashes, often with spaces around them
SEP = r"[-–—\s]{0,3}"
ISBN13 = re.compile(rf"(97[89]{SEP}(?:\d{SEP}){{9}}\d)")
ISBN10_LABELLED = re.compile(rf"ISBN(?:-10)?[:\s]*((?:\d{SEP}){{9}}[\dXx])")
YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
# the place, publisher and year of a catalogue card, which may wrap: "— СПб.: Питер, 2026. —"
CARD_YEAR = re.compile(r"[—-]\s?[^\W\d_][^\W\d_.]*\.?(?:\s?[^\W\d_]+\.?)?\s*:\s*[^—]{1,60}?,\s*"
                       r"((?:19|20)\d{2})\.\s*[—-]")
# the whole catalogue card on the imprint page: "— М.: Дет. лит., 1988.— 47 с.— (Книга за книгой)."
CARD = re.compile(r"[^\n]*?\.\s?[—-]\s?[^\W\d_][^\W\d_]*\.?(?:\s?[^\W\d_]+\.?)?\s?:\s?"
                  r"[^\n]+?,\s?((?:19|20)\d{2})[^\n]*")
CARD_SERIES = re.compile(r"[—-]\s?\(([^()]{3,80})\)\.?\s*$")


# the copyright sign, in any language: "© 2021", "(c) 2019"
COPYRIGHT = re.compile(r"(?:©|\([cC]\))[^\n]{0,120}")
# an edition history by its shape, whatever the month's language: "November 2021: Second Edition"
EDITION_LINE = re.compile(r"^\s*[^\W\d_]{3,12}\.?\s+((?:19|20)\d{2})\s?:\s+\S[^\n]*$", re.M)
# a history is two such lines in a row; one alone is as often a law cited by its year


def isbn_valid(raw: str) -> bool:
    digits = re.sub(r"[-–—\s]", "", raw).upper()
    if len(digits) == 13 and digits.isdigit():
        return sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(digits)) % 10 == 0
    if len(digits) == 10 and digits[:9].isdigit() and (digits[9].isdigit() or digits[9] == "X"):
        return sum((10 - i) * (10 if c == "X" else int(c)) for i, c in enumerate(digits)) % 11 == 0
    return False


# the one way to read an ISBN anywhere: digits and a final X, nothing else
def normalise_isbn(raw) -> str:
    return re.sub(r"[^\dX]", "", str(raw or "").upper())


def isbns(text: str) -> list[str]:
    found = [normalise_isbn(m.group(1)) for pattern in (ISBN13, ISBN10_LABELLED) for m in pattern.finditer(text)
             if isbn_valid(m.group(1))]
    return list(dict.fromkeys(found))


def _history(text: str) -> list[int]:
    found = list(EDITION_LINE.finditer(text))
    paired = [a for a, b in zip(found, found[1:], strict=False) if text.count("\n", a.end(), b.start()) <= 1]
    return [int(m.group(1)) for m in found] if paired else []


# the year of this edition: the edition history, else the catalogue card, else the latest copyright year
def _year(text: str, out: SourceResult) -> None:
    if editions := _history(text):
        out.add("year", max(editions), 0.7, "the latest edition in the edition history")
    elif m := CARD_YEAR.search(text):
        out.add("year", int(m.group(1)), 0.7, f"the catalogue card: {m.group(0)[:80]}")
    elif years := [int(y) for line in COPYRIGHT.findall(text) for y in YEAR.findall(line)]:
        out.add("year", max(years), 0.6, "latest copyright year")


# only what reads the same in every language; the model reading the same pages answers edition, volume, publisher
def read(text: str) -> SourceResult:
    out = SourceResult("title_pages", covers=("isbn", "year", "series"))
    found = isbns(text)
    if found:
        out.add("isbn", found[0], 0.8, f"first ISBN in the title pages; all found: {found}")
    # later ones are often other books advertised in the front matter, or the original of a translation
    for other in found[1:]:
        out.add("_other_isbn", other, 0.2, "a later ISBN in the title pages")
    _year(text, out)
    for m in CARD.finditer(text):
        card = m.group(0)
        if s := CARD_SERIES.search(card):
            out.add("series", s.group(1).strip(), 0.7, f"catalogue card: {card[:160]}")
        break
    return out
