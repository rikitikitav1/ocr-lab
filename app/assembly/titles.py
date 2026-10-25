# when a heading and a structure title are the same title, for the passes, the layouts and the measures
from rapidfuzz import fuzz

SUB_ENTRY_SIMILARITY = 90


# a heading and a structure title are one when they read alike, spacing and case aside, or alike with no space at all
def same_title(a: str, b: str) -> bool:
    if fuzz.WRatio(" ".join(a.split()).lower(), " ".join(b.split()).lower()) >= SUB_ENTRY_SIMILARITY:
        return True
    return fuzz.ratio("".join(a.split()).lower(), "".join(b.split()).lower()) >= SUB_ENTRY_SIMILARITY
