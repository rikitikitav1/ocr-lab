# text entering the stand loses invisible and control characters; private-use ones stay, fonts keep letters there
import re
import unicodedata

LIGATURES = {chr(c): unicodedata.normalize("NFKC", chr(c)) for c in range(0xFB00, 0xFB07)}
# the zero-width joiners (U+200C, U+200D) stay: Farsi spells words with them ("می‌خواهم")
DROPPED = re.compile("[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f­​⁠﻿￾￿]")
SPACES = re.compile("[   -   　]")


def clean(text: str) -> str:
    text = DROPPED.sub("", text)
    text = SPACES.sub(" ", text)
    return "".join(LIGATURES.get(c, c) for c in text)


def deep(value):
    if isinstance(value, str):
        return clean(value)
    if isinstance(value, list):
        return [deep(v) for v in value]
    if isinstance(value, dict):
        return {k: deep(v) for k, v in value.items()}
    return value
