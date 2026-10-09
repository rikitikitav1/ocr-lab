# language shares over body pages, so a mixed book says both
import re
from functools import cache

from lingua import LanguageDetectorBuilder

from stages.metadata.candidates import SourceResult

MIN_SHARE = 0.15
# a plain word, so base64, URLs and code identifiers do not vote
WORD = re.compile(r"[«(\"]?[^\W\d_]{2,24}(?:[-'][^\W\d_]+)?[.,;:!?)»\"]*")


# every language the detector knows: a book's language is never assumed
@cache
def _detector():
    return LanguageDetectorBuilder.from_all_languages().build()


def _code(language) -> str:
    return language.iso_code_639_1.name.lower()


def read(body: str) -> SourceResult:
    out = SourceResult("detector", covers=("languages",))
    if len(body.strip()) < 200:
        return out
    body = " ".join(w for w in body.split() if WORD.fullmatch(w))
    counts: dict[str, int] = {}
    for chunk in [body[i:i + 400] for i in range(0, min(len(body), 40000), 400)]:
        found = _detector().detect_language_of(chunk)
        if found is not None:
            counts[_code(found)] = counts.get(_code(found), 0) + 1
    total = sum(counts.values())
    if not total:
        return out
    shares = {k: round(v / total, 2) for k, v in sorted(counts.items(), key=lambda x: -x[1])}
    languages = [k for k, share in shares.items() if share >= MIN_SHARE]
    out.add("languages", languages, 0.9 if len(languages) == 1 else 0.7, f"shares over body pages: {shares}")
    return out


# the language of a short line such as a title; None when it has too few letters to tell
def of_line(text: str) -> str | None:
    if sum(c.isalpha() for c in text) < 6:
        return None
    found = _detector().detect_language_of(text)
    return _code(found) if found is not None else None
