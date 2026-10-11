# a book knob names the word its chapters open with ("درس" in "درس اول"): a line of that word and one more opens one
import re

import numerals
import pdf
import settings

from stages.toc.sources import Entry, SourceToc

# recognition leaves stray marks at a line's ends (". درس هفتم")
EDGES = re.compile(r"^[\W_]+|[\W_]+$")


def clean(text: str) -> str:
    return EDGES.sub("", " ".join(text.split()))


def is_label(text: str, label: str) -> bool:
    words = clean(text).split()
    return (len(words) == 2 and words[0].casefold() == label.casefold()
            and any(c.isalpha() for c in words[1]) and not any(c.isdigit() for c in words[1]))


# `heads` maps a page to its top lines in order; the first label line on a page opens a chapter there
def read(heads: dict[int, list[str]], label: str, where: str) -> SourceToc:
    out = SourceToc("labels", notes={"label": label})
    for page in sorted(heads):
        title = next((clean(t) for t in heads[page] if is_label(t, label)), None)
        if title is not None:
            out.entries.append(Entry(title, 1, page, evidence=f"{where}, page {page}", verified=True,
                                     source="labels"))
    if len(out.entries) < 2:
        out.failed = f"{len(out.entries)} lines of {label!r} and one word at the top of a page"
    return out


# a label word, then its number in the label's case ("Глава двайсет и първа", "ГЛАВА ПЕРВАЯ"), then a break
LABEL_START = re.compile(r"(?<![\w-])([^\W\d_]{3,})[ \t]+")
WORD = re.compile(r"[^\W_]+")
LABEL_MIN = 3
NUMBER_WORDS = 3


def _number(label: str, words: list[str]) -> int:
    if words and (words[0].isdigit() or numerals.roman(words[0])):
        return 1
    same_case = str.isupper if label.isupper() else str.islower
    taken = 0
    for w in words[:NUMBER_WORDS]:
        if not w.isalpha() or not same_case(w):
            break
        taken += 1
    return taken


def _occurrences(text: str) -> list[tuple[str, str]]:
    out = []
    for m in LABEL_START.finditer(text):
        label = m.group(1)
        if not label[0].isupper():
            continue
        tail = text[m.end():m.end() + 120]
        words = [w.group() for w in WORD.finditer(tail.split("\n")[0])]
        n = _number(label, words)
        # a number word that is the start of the sentence is no number: the break must come right after it
        for size in range(n, 0, -1):
            num = " ".join(words[:size])
            end = tail.find(words[size - 1]) + len(words[size - 1]) if size else 0
            rest = tail[end:]
            nxt = rest.lstrip(" \t")
            if not nxt or nxt[0] in "\n.:,;!?—–-" or (nxt[0].isupper() and not label.isupper()) or nxt[0].isdigit():
                out.append((label, num))
                break
    return out


# a heading word: once a page, its numbers all different, rarer than a name in the prose ("Синдер погледна")
def discover(pages: dict[int, str], set_apart) -> tuple[str, list[tuple[int, str]]] | None:
    found: dict[str, list[tuple[int, str]]] = {}
    for page in sorted(pages):
        for label, num in _occurrences(pages[page]):
            if set_apart(page, f"{label} {num}"):
                found.setdefault(label.casefold(), []).append((page, f"{label} {num}"))
    best = None
    for label, hits in found.items():
        pages_hit = [p for p, _ in hits]
        numbers = [t.split(None, 1)[1].casefold() for _, t in hits]
        if (len(hits) >= LABEL_MIN and len(set(pages_hit)) == len(hits) and len(set(numbers)) == len(numbers)
                and len(hits) * 3 <= len(pages)):
            if best is None or len(hits) > len(best[1]):
                best = (label, hits)
    return best


# a heading stands on its own line by its glyphs, whatever the layer's lines say, centred or set larger than the text
def set_apart(glyphs: list[tuple], heading: str) -> bool:
    chars = "".join(g[4] for g in glyphs)
    key = "".join(heading.split())
    start = chars.find(key)
    if start < 0:
        return False
    own = glyphs[start:start + len(key)]
    top, height = own[0][1], own[0][3] - own[0][1]
    if any(abs(g[1] - top) > height / 2 for g in own):
        return False
    before = glyphs[start - 1] if start else None
    after = glyphs[start + len(key)] if start + len(key) < len(glyphs) else None
    if any(g is not None and abs(g[1] - top) <= height / 2 for g in (before, after)):
        return False
    middle = (own[0][0] + own[-1][2]) / 2
    body = sorted(g[3] - g[1] for g in glyphs)[len(glyphs) // 2]
    return abs(middle - 0.5) <= CENTRED or height >= body * LARGER


CENTRED = 0.15
LARGER = 1.1


def found_in(files, lines: dict[int, list]) -> SourceToc | None:
    by_page = {f.first_page + i: (f, i) for f in files for i in range(f.pages)}

    def apart(page: int, heading: str) -> bool:
        f, index = by_page[page]
        return set_apart(pdf.page_glyphs(settings.DATA_DIR / f.file_path, index), heading)

    got = discover({page: "\n".join(x.text for x in page_lines) for page, page_lines in lines.items()}, apart)
    if got is None:
        return None
    label, hits = got
    return SourceToc("labels", [Entry(title, 1, page, evidence=f"the text layer, page {page}", verified=True,
                                      source="labels") for page, title in hits], notes={"label": label})
