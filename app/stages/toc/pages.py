# printed page numbers turned into book pages: the offset that puts most titles on their own pages
import re
from collections import Counter

import numerals
from rapidfuzz import fuzz

from stages import running_heads
from stages.toc.sources import Entry

MIN_KEY = 8
KEY_CHARS = 40
OFFSETS = range(-40, 120)
LOCAL = 4
NEARLY = 92
SAME_WORDS = 95


norm = running_heads.norm


# repeated top and bottom lines are running heads and are not searched, but for a chapter's opening top
def page_text(lines: dict[int, list], skip: set[int]) -> dict[int, str]:
    heads = running_heads.per_page(lines)
    return {page: norm(" ".join(x.text for i, x in enumerate(page_lines) if i not in heads[page]))
            for page, page_lines in lines.items() if page not in skip}


LABEL = re.compile(rf"^(?:\w+\s+)?(?:\d{{1,3}}(?:\.\d{{1,3}})*|{numerals.ROMAN_LABEL})[.:]?\s+(?=\w)", re.I)


def words(title: str) -> str:
    return re.sub(r"[\W_]+", " ", LABEL.sub("", title.strip(), count=1).lower()).strip()


NUMBER = re.compile(rf"\d{{1,3}}(?:\.\d{{1,3}})*|{numerals.ROMAN_LABEL}")


# a title holding only the label ("Unit I:") is the chapter whose title opens with it
def label_of(short: str, long: str) -> bool:
    x, y = re.findall(r"[^\W_]+", short.lower()), re.findall(r"[^\W_]+", long.lower())
    return 0 < len(x) <= 2 and len(y) > len(x) and y[: len(x)] == x and bool(NUMBER.fullmatch(x[-1]))


# on one page, a title whose words all sit in the other ("Background" in "Background Introduced by X") is it
def same_words(a: str, b: str) -> bool:
    x, y = words(a), words(b)
    return bool(x) and bool(y) and fuzz.token_set_ratio(x, y) >= SAME_WORDS


# the title with and without its label: an opening page often prints "1" big and the title alone
def keys(entry: Entry) -> list[str]:
    whole = norm(entry.title)[:KEY_CHARS]
    bare = norm(LABEL.sub("", entry.title.strip(), count=1))[:KEY_CHARS]
    return [k for k in dict.fromkeys((bare, whole)) if k]


def _on(page_text: dict[int, str], page: int, key: str | list[str]) -> bool:
    text = page_text.get(page, "")
    return any(k in text for k in ([key] if isinstance(key, str) else key))


# a title with one broken glyph in the text layer ("\x81азвертывание") is still on its page
def _nearly_on(page_text: dict[int, str], page: int, keys: list[str]) -> bool:
    text = page_text.get(page, "")
    return any(len(k) >= MIN_KEY and fuzz.partial_ratio(k, text) >= NEARLY for k in keys)


def best_offset(entries: list[Entry], page_text: dict[int, str]) -> tuple[int | None, int]:
    votes = Counter()
    for e in entries:
        key = [k for k in keys(e) if len(k) >= MIN_KEY]
        if e.printed is None or not e.printed.isdigit() or not key:
            continue
        first = next((d for d in OFFSETS if _on(page_text, int(e.printed) + d, key)), None)
        if first is not None:
            votes[first] += 1
    if not votes:
        return None, 0
    d, n = votes.most_common(1)[0]
    return d, n


# each title is looked for near the offset, which inserted plates shift; one not found is unverified
def place(entries: list[Entry], page_text: dict[int, str], pages: int) -> dict:
    offset, votes = best_offset(entries, page_text)
    verified = unverified = 0
    local = offset
    for e in entries:
        if e.printed is None:
            continue
        key = keys(e)
        if e.printed.isdigit():
            if offset is None:
                continue
            guess = int(e.printed) + offset
        else:
            value = numerals.roman(e.printed)
            if value is None:
                continue
            guess = value
        # the offset page when the title is there, else the first page nearby with it: later ones are running heads
        found = [p for p in range(guess - LOCAL, guess + LOCAL + 1) if key and _on(page_text, p, key)]
        if guess not in found and _nearly_on(page_text, guess, key):
            found = [guess, *found]
        if found:
            e.page = guess if guess in found else found[0]
            e.verified = True
            verified += 1
            if e.printed.isdigit():
                local = e.page - int(e.printed)
        elif e.printed.isdigit():
            # a title not found takes the offset of the last one found, which follows inserted plates
            e.page = int(e.printed) + local
            unverified += 1
        if e.page is not None:
            e.page = min(max(e.page, 1), pages)
    # a part title without a page goes to its own page just before the next placed entry, if printed there
    for i, e in enumerate(entries):
        if e.page is not None or e.printed is not None:
            continue
        nxt = next((x.page for x in entries[i + 1:] if x.page is not None), None)
        if nxt is not None:
            before = [p for p in range(nxt - 1, max(nxt - LOCAL, 1) - 1, -1) if _on(page_text, p, keys(e))]
            e.page = before[0] if before else nxt
    return {"offset": offset, "offset_votes": votes, "verified": verified, "unverified": unverified,
            "unplaced": sum(e.page is None for e in entries)}
