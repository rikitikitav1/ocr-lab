# the caption element in the blocks: captions back from furniture and the series' captions set apart
from document.model import Caption, Code, Figure, Heading, PageMarker, Paragraph, Table

from elements import furniture


# a caption of the book's series an engine set aside as furniture comes back after the picture, table or listing
def captions_from_furniture(blocks: list, reads: dict, picked: dict,
                            captions: dict[int, list[str]]) -> tuple[list, int]:
    book_page = {b.file_page: b.book_page for b in blocks if isinstance(b, PageMarker)}

    def claims(page: int, text: str) -> bool:
        return any(_caption_cut(text, w) is not None for w in captions.get(book_page.get(page), []))

    back = {page: [Caption(text=" ".join(t.split())) for t in texts]
            for page, texts in furniture.taken_back(reads, picked, claims).items()}
    out, page, n = [], None, 0
    for b in blocks:
        if isinstance(b, PageMarker):
            page = b.file_page
        out.append(b)
        if back.get(page) and isinstance(b, (Figure, Table, Code)):
            out.append(back[page].pop(0))
            n += 1
    return out, n


# a block opening with a caption of the book's own series is that caption, the paragraph's rest after it stays
def series_captions(blocks: list, captions: dict[int, list[str]]) -> tuple[list, int]:
    out, page, n = [], None, 0
    for k, b in enumerate(blocks):
        if isinstance(b, PageMarker):
            page = b.book_page
        wanted = captions.get(page, []) if page is not None else []
        if wanted and isinstance(b, (Paragraph, Heading)) and not (isinstance(b, Heading) and b.node is not None) \
                and _names_something(blocks, k):
            cut = next((c for w in wanted if (c := _caption_cut(b.text, w)) is not None), None)
            if cut is not None:
                head, rest = b.text[:cut].strip(), b.text[cut:].strip()
                out.append(Caption(text=head, where=b.where))
                if rest:
                    out.append(Paragraph(text=rest, where=b.where))
                n += 1
                continue
        out.append(b)
    return out, n


CAPTION_PREFIX = 0.9


# a caption stands by what it names: a picture, a table or a listing within this many blocks on its page
CAPTION_REACH = 2


def _names_something(blocks: list, k: int) -> bool:
    for step in (-1, 1):
        for j in range(k + step, k + step * (CAPTION_REACH + 1), step):
            if not 0 <= j < len(blocks) or isinstance(blocks[j], PageMarker):
                break
            if isinstance(blocks[j], (Figure, Table, Code)):
                return True
    return False


# where a caption's letters end inside a block that opens with them, or None when the block does not open with them
def _caption_cut(text: str, caption: str) -> int | None:
    at = [i for i, c in enumerate(text) if not c.isspace()]
    letters, want = "".join(text[i] for i in at), "".join(caption.split())
    pairs = zip(letters, want, strict=False)
    same = next((k for k, (a, b) in enumerate(pairs) if a != b), min(len(letters), len(want)))
    if not want or same < CAPTION_PREFIX * len(want) and same < len(letters):
        return None
    return at[same - 1] + 1 if same else None
