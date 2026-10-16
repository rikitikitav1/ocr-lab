# numbers as books print them; the stdlib has no Roman numerals, so their one well-formed pattern lives here
import re

_UPPER = r"(?=[MDCLXVI])M{0,3}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3})"
# a chapter or part number stops at C: "D. Conclusion" and "M. Smith" open with a letter
_UPPER_LABEL = r"(?=[CLXVI])C{0,3}(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3})"

# one case throughout ("XIV", "xiv"), so "Civil" is a word; safe inside a pattern compiled with re.I
ROMAN = rf"(?:(?-i:{_UPPER})|(?-i:{_UPPER.lower()}))"
ROMAN_LABEL = rf"(?:(?-i:{_UPPER_LABEL})|(?-i:{_UPPER_LABEL.lower()}))"
# upper case only, for numbered titles where a lower-case word must stay a word ("i. e.", "v.")
ROMAN_LABEL_UPPER = rf"(?-i:{_UPPER_LABEL})"
ARABIC = r"\d{1,4}"
# a page number as a contents line or a page edge prints it
PAGE = rf"(?:{ARABIC}|{ROMAN})"

# a label over a title ("ГЛАВА 1", "PART I", "3"); a Roman one from C up reads as an acronym ("Using CLI")
LABEL_LINE = re.compile(rf"^\s*(?:[^\W\d_]+\s+)?(?:\d{{1,3}}|(?!c){ROMAN_LABEL})\s*[.:]?\s*$", re.I)

_WHOLE = re.compile(rf"^{ROMAN}$")
_DIGITS = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}


def roman(text: str) -> int | None:
    if not text or not _WHOLE.match(text):
        return None
    letters = text.upper()
    total = 0
    for a, b in zip(letters, letters[1:] + " ", strict=True):
        total += -_DIGITS[a] if b != " " and _DIGITS[a] < _DIGITS[b] else _DIGITS[a]
    return total


def value(text: str) -> int | None:
    return int(text) if text.isdigit() else roman(text)
