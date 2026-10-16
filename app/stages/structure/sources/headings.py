# a book's top nodes from the headings of its pages read as pictures: headings grouped by look, one group the top nodes
import collections
import functools
import math
import re
import statistics

import numerals

from stages.structure.sources import Entry, SourceEntries, conf

TITLE_TYPES = ("doc_title", "title", "paragraph_title")
NUMBER = rf"(?:\d{{1,3}}|{numerals.ROMAN_LABEL_UPPER})"
LABELLED = re.compile(rf"^([^\W\d_]{{3,}})\s+(?=\w)({NUMBER})(?!\w)")
NUMBERED = re.compile(r"^(\d{1,3}(?:\.\d{1,3})*)[.)]?\s+\S")
# a number standing alone: "SQL" holds no L and "BASIC 3" runs 3
RUNNING = re.compile(rf"(?<!\w)(?=\w)({NUMBER})(?!\w)")
DASHES = ("—", "-", "–")


# a bare "Chapter 3" block, its word one of the configured part and chapter labels
@functools.cache
def _bare_label() -> re.Pattern:
    words = (*conf()["text_layer"]["numbering"]["part"], *conf()["text_layer"]["numbering"]["chapter"])
    alternatives = "|".join(re.escape(w) for w in words)
    if not alternatives:
        return re.compile(r"(?!)")
    return re.compile(rf"^(?:{alternatives})\s+(?:{NUMBER}|(?-i:[A-Z]))\.?$", re.I)


def _norm(text: str) -> str:
    return re.sub(r"[^\w]+", " ", text.lower()).strip()


def blocks(layouts: dict[int, dict], text_of) -> list[dict]:
    out = []
    for page, layout in sorted(layouts.items()):
        for b in layout.get("blocks") or []:
            text = " ".join(text_of(b).split())
            x0, y0, x1, y1 = b.get("bbox") or (0, 0, 0, 0)
            if not text or x1 <= x0 or y1 <= y0:
                continue
            # a type size in thousandths of the page from the box area per character, so long lines read a little small
            size = math.sqrt((x1 - x0) * (y1 - y0) / (0.66 * len(text))) * 1000
            out.append({"page": page, "type": b.get("type"), "text": text, "size": size, "words": len(text.split())})
    return out


def _repeats(cand: list[dict], total: int):
    c = conf()["scan_layer"]["headings"]

    # a running head carries its page number and its node's name, so it repeats apart from the title it copies
    def key(b):
        k = _norm(b["text"])
        header = b["type"] == "header"
        return (header, re.sub(r"\d+", "", k).strip() if header else k)

    pages_of = collections.defaultdict(set)
    for b in cand:
        pages_of[key(b)].add(b["page"])

    def repeated(b):
        ps = sorted(pages_of[key(b)])
        n = c["repeat_run"]
        run = any(ps[i + n - 1] - ps[i] == n - 1 for i in range(len(ps) - n + 1))
        return len(ps) >= max(n, c["repeat_share"] * total) or run

    return key, repeated


def candidates(bl: list[dict], total: int) -> tuple[float, list[dict]]:
    c = conf()["scan_layer"]["headings"]
    body = statistics.median([b["size"] for b in bl if b["type"] == "text" and b["words"] >= 20] or [10])
    # a block typed header is a guess from its place on the page: node titles at a page's top get it too
    def short(b):
        return b["words"] <= c["max_words"] or (b["type"] == "doc_title" and b["words"] <= c["doc_title_max_words"])

    cand = [b for b in bl if b["type"] in (*TITLE_TYPES, "text", "header") and short(b)
            and not b["text"].startswith(DASHES)
            and (b["type"] != "text" or (b["size"] > body * c["text_larger"] and b["words"] <= c["text_max_words"]))]
    key, repeated = _repeats(cand, total)
    heads = [b["size"] for b in cand if b["type"] == "header" and key(b)[1] and repeated(b)]
    kept = [b for b in cand if key(b)[1] and not repeated(b)]
    # the repeated header blocks are the running heads; a single header block of their size is one too
    if len(heads) >= c["head_min"]:
        cap = statistics.median(heads) * c["head_larger"]
        kept = [b for b in kept if not (b["type"] == "header" and b["size"] <= cap)]
    return body, _glued(kept)


# a bare "Chapter n" block takes the next candidate on its page as its title, keeping its own size and type
def _glued(cand: list[dict]) -> list[dict]:
    out, skip = [], False
    for i, b in enumerate(cand):
        if skip:
            skip = False
            continue
        nxt = cand[i + 1] if i + 1 < len(cand) else None
        if _bare_label().match(b["text"]) and nxt and nxt["page"] == b["page"] and not _bare_label().match(nxt["text"]):
            out.append({**b, "text": f"{b['text']} {nxt['text']}", "words": b["words"] + nxt["words"]})
            skip = True
        else:
            out.append(b)
    return out


# a heading's look apart from its size: a label word with a number, a dotted number of some depth, or none
def kind(text: str) -> tuple | None:
    m = LABELLED.match(text)
    if m:
        return ("label", m.group(1).lower())
    m = NUMBERED.match(text)
    if m:
        return ("number", m.group(1).count("."))
    return None


def _size_steps(group: list[dict]) -> list[list[dict]]:
    out, last = [], None
    for b in sorted(group, key=lambda b: b["size"]):
        if last is None or b["size"] > last * conf()["scan_layer"]["headings"]["style_step"]:
            out.append([])
        out[-1].append(b)
        last = b["size"]
    return out


# headings of one look split where the size steps up; the rest grouped by size alone; the largest first
def style_groups(cand: list[dict]) -> list[list[dict]]:
    by_kind, rest = collections.defaultdict(list), []
    for b in cand:
        k = kind(b["text"])
        (by_kind[k] if k else rest).append(b)
    kinds = [part for g in by_kind.values() for part in _size_steps(g)]
    groups = [g for g in kinds if len(g) >= 2]
    rest += [b for g in kinds if len(g) < 2 for b in g]
    groups += _size_steps(rest)
    return sorted(groups, key=lambda g: -statistics.median(x["size"] for x in g))


# most titles carry a number, and the numbers mostly rise in page order
def running_number(group: list[dict]) -> bool:
    c = conf()["scan_layer"]["headings"]
    nums = []
    for b in sorted(group, key=lambda b: b["page"]):
        if m := RUNNING.search(b["text"]):
            n = m.group(1)
            nums.append(int(n) if n.isdigit() else numerals.value(n))
    nums = [n for n in nums if n is not None]
    if len(nums) < c["numbered_share"] * len(group) or len(nums) < 2:
        return False
    return sum(b > a for a, b in zip(nums, nums[1:], strict=False)) >= c["rising_share"] * (len(nums) - 1)


# the pages up to a contents printed at the book's start are its front matter: title, series, publisher lines
def front_end(contents: frozenset[int]) -> int:
    head = [p for p in contents if p <= conf()["contents"]["scan_head"]]
    return max(head) if head else 0


def read(layouts: dict[int, dict], total: int, text_of, contents: frozenset[int] = frozenset()) -> SourceEntries:
    c = conf()["scan_layer"]["headings"]
    out = SourceEntries("headings")
    _, cand = candidates(blocks(layouts, text_of), total)
    cut = front_end(contents)
    cand = [b for b in cand if b["page"] > cut]
    groups = style_groups(cand)

    def spread(g):
        ps = [b["page"] for b in g]
        return max(ps) - min(ps) >= c["node_spread"] * total

    eligible = [i for i, g in enumerate(groups) if len(g) >= c["min_nodes"] and spread(g)]
    out.notes = {"candidates": len(cand), "groups": len(groups), "eligible": len(eligible), "front_end": cut}
    if not eligible:
        out.failed = (f"no group of {c['min_nodes']} or more headings of one look spread over "
                      f"{c['node_spread']:.0%} of the book among {len(cand)} candidates")
        return out
    pick = next((i for i in eligible if running_number(groups[i])), eligible[0])
    entries = []
    for i, g in enumerate(groups):
        # a larger group joins the top nodes unless it runs a number (parts); a smaller one sits below them
        if i < pick:
            level = 0 if len(g) >= c["min_nodes"] and running_number(g) else 1
        elif i == pick:
            level = 1
        else:
            level = 2 + sum(1 for j in range(pick + 1, i) if len(groups[j]) >= 2)
        entries += [(b["page"], level, b["text"]) for b in g]
    top = min(level for _, level, _ in entries)
    tops = sum(level == top for _, level, _ in entries)
    # a reference manual's every subhead taken for a node: more top nodes than half the pages is no structure
    if tops > c["max_nodes_per_page"] * total:
        out.failed = f"{tops} top nodes in {total} pages: more than {c['max_nodes_per_page']} a page"
        return out
    out.entries = [Entry(title, level - top + 1, page, evidence=f"a heading read on page {page}", verified=True,
                         source="headings") for page, level, title in sorted(entries, key=lambda e: e[0])]
    out.notes["nodes"] = len(groups[pick])
    return out
