# the letters a book's languages write, from CLDR's exemplar sets as Google Fonts ships them, and plain ASCII
import functools
import string

import gflanguages

PRIVATE_USE = range(0xE000, 0xF900)


@functools.cache
def _languages() -> dict:
    return gflanguages.LoadLanguages()


@functools.cache
def letters(languages: tuple[str, ...]) -> frozenset[str]:
    out = set(string.ascii_letters)
    for key, language in _languages().items():
        if key.split("_")[0] in languages:
            for chars in (language.exemplar_chars.base, language.exemplar_chars.auxiliary):
                out |= {c for c in chars if c.isalpha()}
    return frozenset(out | {c.lower() for c in out} | {c.upper() for c in out})


# a letter none of the book's languages writes, or a private-use glyph, which a broken font encoding leaves
def foreign(c: str, alphabet: frozenset[str]) -> bool:
    return (c.isalpha() or ord(c) in PRIVATE_USE) and c not in alphabet
