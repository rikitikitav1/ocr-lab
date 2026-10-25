# the footnote element: an engine's note split into mark and text, the page layout's note lines, a note set aside
import re

from document.model import Footnote, PageMarker, Paragraph

from elements import folding

FOOTNOTE_MARK = re.compile(r"^\s*(\d{1,3}|[*†‡§¶]{1,3})\s+(.+)$", re.S)


# an engine's footnote block split into its mark and text; one printed without a mark is numbered apart
class Notes:
    def __init__(self):
        self.unmarked = 0

    def read(self, text: str) -> Footnote:
        if m := FOOTNOTE_MARK.match(text):
            return Footnote(mark=m.group(1), text=m.group(2).strip())
        # a note printed without a mark gets one that cannot clash with the book's own numbers
        self.unmarked += 1
        return Footnote(mark=f"note{self.unmarked}", text=text.strip())


# the lines the page layout reads as notes, per book page, joined and spaced for a word-bounded search
def note_text(lines: dict, notes: set[int]) -> dict[int, str]:
    return {p: " " + " ".join(" ".join(x.text for x in ls if id(x) in notes).split()).casefold() + " "
            for p, ls in lines.items() if any(id(x) in notes for x in ls)}


NOTE_HEAD_WORDS = 6
NOTE_MIN_WORDS = 3


# a footnote an engine set aside as furniture comes back at its page's end when the page layout reads it as a note
def notes_from_furniture(blocks: list, reads: dict, picked: dict, notes: dict[int, str]) -> tuple[list, int]:
    back: dict[int, list[Paragraph]] = {}
    for page, pick in picked.items():
        if page not in notes:
            continue
        for at, _, text in getattr(reads[pick["picked"]], "furniture_at", []):
            words = folding.fold(text).split()
            if at == page and len(words) >= NOTE_MIN_WORDS and f" {' '.join(words[:NOTE_HEAD_WORDS])} " in notes[page]:
                back.setdefault(page, []).append(Paragraph(text=" ".join(text.split())))
    if not back:
        return blocks, 0
    out, page = [], None
    for b in blocks:
        if isinstance(b, PageMarker):
            out += back.get(page, [])
            page = b.file_page
        out.append(b)
    out += back.get(page, [])
    return out, sum(map(len, back.values()))
