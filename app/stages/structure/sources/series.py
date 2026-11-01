# a contents' levels from its numbering: a series starting again names its parent, so forms nest as the book sets them
import re
from collections import Counter, defaultdict

import numerals

DOTTED = re.compile(r"^\d+(?:\.\d+)+\.?\s*\S")
BARE = re.compile(r"^\d{1,3}\.?\s+[^\W\d_]")
MARKED = re.compile(r"^\S+?[.:)]\s")
NUMBER_FIRST = re.compile(r"^\d{1,3}\.?\s")
LABEL = "label:"
# a word and its number before a title: a number in words needs the colon, or any two words would do
LABELLED = re.compile(r"^(?P<word>[^\W\d_]{3,})\s+(?:§\s*)?"
                      r"(?P<num>(?:\d{1,3}(?!\.\d)|[IVXLC]+)(?=[.:\s—–-]|$)|[^\W\d_]+(?=[.:—–]))")
FORMS = (("roman", re.compile(r"^[IVXLC]+[.:)]?\s+\S")), ("upper", re.compile(r"^[A-Z][.)]\s+\S")),
         ("arabic", re.compile(r"^\d{1,3}[.:)]?\s+\S")), ("lroman", re.compile(r"^[ivxl]+[.)]\s+\S")),
         ("lower", re.compile(r"^[a-z][.)]\s+\S")),
         ("double", re.compile(r"^[a-z]{2}[.)]\s+\S")), ("parend", re.compile(r"^\(\d{1,3}\)\s+\S")),
         ("parenl", re.compile(r"^\([a-z]{1,3}\)\s+\S")))
# letters that are Roman numerals too: the series around them tells which
AMBIGUOUS = frozenset("CDILVX")
# this many forms, each seen this often, on this share of the entries, say the numbering carries the levels
MIN_FORMS = 3
MIN_SEEN = 2
MIN_SHARE = 0.5
# a series starting this often names its parent even out of the unnumbered lines before it
MIN_STARTS = 2


def _form(title: str) -> str | None:
    if DOTTED.match(title):
        return f"dotted{title.split()[0].rstrip('.').count('.')}"
    if form := next((name for name, rx in FORMS if rx.match(title)), None):
        return form
    labelled = LABELLED.match(title)
    return LABEL + labelled["word"].lower() if labelled else None


def _value(form: str | None, token: str, title: str) -> int | None:
    if form in ("roman", "lroman"):
        return numerals.roman(token.upper())
    if form == "upper":
        return ord(token[0]) - 64
    if form in ("lower", "double", "parenl"):
        return ord(token[0]) - 96
    if form in ("arabic", "parend"):
        return int(token) if token.isdigit() else None
    if form and form.startswith(LABEL):
        return None
    if form:
        tail = title.split()[0].rstrip(".").split(".")[-1]
        return int(tail) if tail.isdigit() else None
    return None


# a letter following the last letter is a letter, an I or the next numeral is Roman, else a letter
def _settled(token: str, last_letter: str | None, last_numeral: int) -> bool:
    follows = last_letter and ord(token) == ord(last_letter) + 1
    return not follows and (token.upper() == "I" or numerals.roman(token.upper()) == last_numeral + 1)


def _typed(titles: list[str]) -> list[tuple[str | None, int | None]]:
    last_upper, last_lower, last_roman, last_lroman = None, None, 0, 0
    rows = []
    for title in titles:
        form = _form(title)
        token = re.split(r"[\s.:)]", title.lstrip("("), maxsplit=1)[0] if form else ""
        if form in ("roman", "upper") and token in AMBIGUOUS:
            form = "roman" if _settled(token, last_upper, last_roman) else "upper"
        elif form == "lroman" and len(token) == 1 and not _settled(token, last_lower, last_lroman):
            form = "lower"
        value = _value(form, token, title)
        if form == "roman":
            last_roman = value or last_roman
        elif form == "lroman":
            last_lroman = value or last_lroman
        elif form == "upper":
            last_upper = token[0]
        elif form == "lower":
            last_lower = token[0]
        rows.append((form, value))
    return _labels_settled(rows, titles)


# a label's series starts again at the number it first came with; a word seen once labels no series
def _labels_settled(rows: list[tuple[str | None, int | None]],
                    titles: list[str]) -> list[tuple[str | None, int | None]]:
    seen = Counter(form for form, _ in rows if form and form.startswith(LABEL))
    first: dict[str, str] = {}
    out = []
    for (form, value), title in zip(rows, titles, strict=True):
        if form and form.startswith(LABEL):
            if seen[form] < MIN_SEEN:
                form = None
            else:
                number = LABELLED.match(title)["num"]
                value = 1 if first.setdefault(form, number) == number else None
        out.append((form, value))
    return out


def _parents(rows: list[tuple[str | None, int | None]]) -> dict[str, str | None]:
    votes: dict[str, Counter] = defaultdict(Counter)
    for i, (form, value) in enumerate(rows):
        if form and value == 1 and i:
            votes[form][rows[i - 1][0]] += 1
    out = {}
    for form, seen in votes.items():
        others = [p for p, _ in seen.most_common() if p != form]
        if seen.total() >= MIN_STARTS:
            out[form] = others[0] if others else None
        elif others and others[0] is not None and not form.startswith(LABEL):
            out[form] = others[0]
    # the rarer label stands above the commoner it breaks up: tops stand apart, the level under them runs on
    labels = Counter(form for form, _ in rows if form and form.startswith(LABEL))
    forms = [form for form, _ in rows]
    for commoner in labels:
        last = len(forms) - 1 - forms[::-1].index(commoner)
        among = [f for f in labels if labels[f] < labels[commoner] and f in forms[forms.index(commoner):last]]
        if among and commoner not in out:
            out[commoner] = max(among, key=labels.__getitem__)
    return out


def _depth(form: str, parents: dict[str, str | None], path: tuple = ()) -> int:
    if form in path or form not in parents:
        return 0
    parent = parents[form]
    if parent is None:
        return 1
    return 0 if parent in path else 1 + _depth(parent, parents, (*path, form))


# a line that carries a number or a label of its own form
def numbered(text: str) -> bool:
    form = _form(text.strip())
    return form is not None and not form.startswith(LABEL)


# a line opening an entry of its own: a bare number inside a wrapped title ("3 May") only under a label
def opens_entry(text: str, under_label: bool) -> bool:
    text = text.strip()
    form = _form(text)
    if form is None or (form == "arabic" and not under_label):
        return False
    # a letter or numeral without its mark may be a wrapped title's first word: "C Language 17"
    if form in ("roman", "upper"):
        return MARKED.match(text) is not None
    if not form.startswith(LABEL):
        return True
    m = LABELLED.match(text)
    return numerals.value(m["num"]) is not None and len(text.split()) > 2


def label_of(title: str) -> str | None:
    labelled = LABELLED.match(title.strip())
    return labelled["word"].lower() if labelled else None


# a word before different numbers is a label: the commonest is the chapter's unless it breaks up bare numbers
def label_depths(titles: list[str], bare: bool = True, standing: list[bool] | None = None) -> dict[str, int]:
    matches = [LABELLED.match(title.strip()) for title in titles]
    words = [m["word"].lower() if m else None for m in matches]
    numbers: dict[str, set[str]] = defaultdict(set)
    for word, m in zip(words, matches, strict=True):
        if word:
            numbers[word].add(m["num"])
    seen = Counter(word for word in words if word)
    labels = [word for word in seen if len(numbers[word]) >= MIN_SEEN]
    common = max(labels, key=seen.__getitem__, default=None)
    if common is None:
        return {}
    first, last = words.index(common), len(words) - 1 - words[::-1].index(common)
    breaks_numbers = bare and any(NUMBER_FIRST.match(title.strip()) for title in titles[first:last])
    depths = {common: -1 if breaks_numbers else 0}
    for word in seen:
        at = [i for i, other in enumerate(words) if other == word]
        if word == common:
            continue
        # tops stand apart: common entries between them, or a lone one set apart by its line right before a chapter
        lone = bool(standing) and standing[at[0]] and numerals.value(matches[at[0]]["num"]) is not None
        apart = common in words[at[0]:at[-1]] or (lone and words[at[0] + 1:at[0] + 2] == [common])
        if at[0] < last and apart:
            depths[word] = -1
        elif word in labels:
            depths[word] = 0
    return depths


# numbers alone, 1 and 1.2, already say their depth; other forms need the series to tell
def mixed(titles: list[str]) -> bool:
    forms = {form for form, _ in _typed(titles) if form and not form.startswith(LABEL)}
    return any(form != "arabic" and not form.startswith("dotted") for form in forms)


# levels from 0, or None when the numbering does not carry them
def nesting(titles: list[str], xs: list[float], gap: float) -> list[int] | None:
    rows = _typed(titles)
    seen = Counter(form for form, _ in rows if form and not form.startswith(LABEL))
    kept = [form for form, n in seen.items() if n >= MIN_SEEN]
    if len(kept) < MIN_FORMS or sum(seen[form] for form in kept) < MIN_SHARE * len(rows):
        return None
    parents = _parents(rows)
    depth = {form: _depth(form, parents) for form, _ in rows if form}
    least = min(depth.values())
    first = next(form for form, _ in rows if form and depth[form] == least)
    at = [i for i, (form, _) in enumerate(rows) if form == first]
    edge = sorted(xs[i] for i in at)[len(at) // 2] + gap
    # unnumbered lines out at the edge between a numbered top series' members are the level above it
    above = not first.startswith(LABEL) and any(rows[i][0] is None and xs[i] <= edge for i in range(at[0] + 1, at[-1]))
    levels: list[int] = []
    for i, (form, _) in enumerate(rows):
        if form:
            levels.append(depth[form] + above)
        else:
            levels.append(levels[-1] if xs[i] > edge and levels else 0)
    # a level holding no line is no level
    rank = {level: n for n, level in enumerate(sorted(set(levels)))}
    return [rank[level] for level in levels]
