# a book's heading layout: each structure level's style read at its nodes' pins, and the labels set above them
from collections import Counter, defaultdict

import numerals
from assembly import passes
from rapidfuzz import fuzz

LABEL = numerals.LABEL_LINE
HOLDS = 0.8


def _pin(ls: list, title: str):
    pairs = [(i, ls[i].text + " " + ls[i + 1].text, True) for i in range(len(ls) - 1)]
    singles = [(i, x.text, False) for i, x in enumerate(ls)]
    fits = [(fuzz.ratio(t.lower(), title.lower()), not joined, i, joined) for i, t, joined in pairs + singles
            if len(t.split()) <= 2 * len(title.split()) + 2 and passes.same_title(t, title)]
    if not fits:
        return None, None
    _, _, i, joined = max(fits)
    if not joined:
        return ls[i], None
    upper, lower = ls[i], ls[i + 1]
    # the label is told by its shape, else the larger line is the heading
    if bool(LABEL.match(upper.text)) != bool(LABEL.match(lower.text)):
        return (lower, upper) if LABEL.match(upper.text) else (upper, lower)
    return (lower, upper) if lower.size > upper.size else (upper, lower)


def measure(lines: dict, taken: set[int], nodes: list[dict]) -> dict:
    styles, labels, counts = defaultdict(Counter), defaultdict(Counter), Counter(n["level"] for n in nodes)
    for node in nodes:
        for page in (node["first_page"], node["first_page"] + 1):
            ls = sorted((x for x in lines.get(page, []) if id(x) not in taken), key=lambda x: x.top)
            heading, label = _pin(ls, node["title"])
            if heading is not None:
                styles[node["level"]][(round(heading.size), heading.bold)] += 1
                # the other line of a pair is a label only in a label's shape, else the heading's wrapped half
                if label is not None and LABEL.match(label.text):
                    labels[node["level"]][(round(label.size), label.bold)] += 1
                break
    levels = []
    for level in sorted(counts):
        pinned = sum(styles[level].values())
        style = styles[level].most_common(1)[0] if pinned else None
        label = labels[level].most_common(1)[0] if labels[level] else None
        in_style = style[1] if style else 0
        # with fewer than 3 pins a level has no style to tell, which is not a level that fails
        holds = None if pinned < 3 else pinned >= HOLDS * counts[level] and in_style >= HOLDS * pinned
        levels.append({"level": level, "nodes": counts[level], "pinned": pinned,
                       "size": style[0][0] if style else None, "bold": style[0][1] if style else None,
                       "in_style": in_style, "holds": holds,
                       "label": {"size": label[0][0], "bold": label[0][1], "count": label[1]}
                       if label and label[1] >= 3 else None})
    return {"levels": levels}
