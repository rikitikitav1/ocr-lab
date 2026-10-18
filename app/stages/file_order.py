# files ordered by the chapter number each prints biggest: unnumbered first, then numbers, then letters
import re
from pathlib import Path

import text_layer

LOOK_PAGES = 4
NUMBER = re.compile(r"^(?:\d{1,3}|[A-Z])$")


def chapter_mark(path: Path) -> str | None:
    pages = text_layer.page_lines(path, list(range(LOOK_PAGES)))
    for index in sorted(pages):
        lines = [x for x in pages[index] if x.text.strip()]
        if not lines:
            continue
        biggest = max(lines, key=lambda x: x.size)
        if NUMBER.match(biggest.text.strip()):
            return biggest.text.strip()
    return None


def sort_key(position: int, mark: str | None) -> tuple:
    if mark is None:
        return 0, 0, position
    if mark.isdigit():
        return 1, int(mark), position
    return 2, ord(mark), position


def by_number(sources: list[tuple[Path, str]]) -> tuple[list[tuple[Path, str]], list[str | None]]:
    marks = [chapter_mark(path) for path, _ in sources]
    ranked = sorted(range(len(sources)), key=lambda i: sort_key(i, marks[i]))
    return [sources[i] for i in ranked], [marks[i] for i in ranked]
