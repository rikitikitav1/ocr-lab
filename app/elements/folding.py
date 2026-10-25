# the word forms the elements match lines by: whitespace folded to one space, case folded
def fold(text: str) -> str:
    return " ".join(text.split()).casefold()


# where a block's words stand inside a line's words, at word boundaries, once
def span(line: list[str], block: list[str]) -> tuple[int, int] | None:
    found = [i for i in range(len(line) - len(block) + 1) if block and line[i:i + len(block)] == block]
    return (found[0], found[0] + len(block)) if len(found) == 1 else None
