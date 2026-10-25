# the footnote element, learned from the book: the lines its page layout reads as notes
from elements import folding


# the lines the page layout reads as notes, per book page, joined and spaced for a word-bounded search
def note_text(lines: dict, notes: set[int]) -> dict[int, str]:
    return {p: f" {folding.fold(' '.join(x.text for x in ls if id(x) in notes))} "
            for p, ls in lines.items() if any(id(x) in notes for x in ls)}
