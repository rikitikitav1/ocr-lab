# the body element: the size and weight a book's text is set in, learned from what its pages open with
from collections import Counter

OPENING = 3
MIN_WORDS = 4
# the opening's style must set this share of the book's characters, or a few page tops would elect it
FLOOR = 0.25


# the style most characters are set in: notes that outweigh the body elect themselves here, so it is the fallback
def by_characters(lines: dict[int, list]) -> tuple[float, bool]:
    styles: Counter = Counter()
    for page_lines in lines.values():
        for line in page_lines:
            styles[(line.size, line.bold)] += len(line.text)
    return styles.most_common(1)[0][0] if styles else (0, False)


# a page's text opens under its running slots and its notes sit at the foot, so the opening lines are the body's
def learn(lines: dict[int, list], band: frozenset[int] = frozenset()) -> tuple[float, bool]:
    most = by_characters(lines)
    if not band:
        return most
    opening: Counter = Counter()
    for page_lines in lines.values():
        kept = [x for x in sorted(page_lines, key=lambda x: x.top)
                if id(x) not in band and len(x.text.split()) >= MIN_WORDS]
        opening.update((x.size, x.bold) for x in kept[:OPENING])
    if not opening:
        return most
    size, bold = opening.most_common(1)[0][0]
    chars = [(x.size, len(x.text)) for page_lines in lines.values() for x in page_lines]
    total = sum(n for _, n in chars)
    held = sum(n for s, n in chars if abs(s - size) < 0.5)
    return (size, bold) if total and held >= FLOOR * total else most
