# lines an engine set aside as page furniture, taken back where the book's own element claims them
from collections.abc import Callable


def taken_back(reads: dict, picked: dict, claims: Callable[[int, str], bool]) -> dict[int, list[str]]:
    back: dict[int, list[str]] = {}
    for page, pick in picked.items():
        for at, _, text in getattr(reads[pick["picked"]], "furniture_at", []):
            if at == page and claims(page, text):
                back.setdefault(page, []).append(text)
    return back
