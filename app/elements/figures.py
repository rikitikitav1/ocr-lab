# the figure element: a picture cut from its page by the box an engine drew, and whether the bundle holds it as a file
import re
from collections.abc import Callable

from document.model import Caption, Figure, Piece


# a figure is linked only when its image is a file in the bundle
def image_kept(image: str) -> bool:
    return re.fullmatch(r"[\w./-]+\.(png|jpe?g|gif|svg|webp)", image) is not None


# a figure's picture is cut from the page by its box, so it does not depend on what an engine exports
def kept(path, blocks: list, keep: Callable[[bytes], str]) -> list:
    # the renderer is loaded here, so the Markdown writer, which only asks image_kept, runs without PyMuPDF
    import pdf

    out = []
    for block in blocks:
        if isinstance(block, Figure) and block.where is not None and not image_kept(block.image):
            block = block.model_copy(update={"image": keep(pdf.page_crop(path, block.where.page - 1,
                                                                          block.where.box))})
        out.append(block)
    return out


def counts(piece: Piece) -> dict:
    figures = [b for b in piece.blocks if isinstance(b, Figure)]
    return {"figures": len(figures), "figures_not_kept": sum(not image_kept(b.image) for b in figures)}


# a caption block right by a figure on its page, the one after it first, is that figure's own; each is taken once
def captioned(blocks: list) -> tuple[list, int]:
    out, taken, n = list(blocks), set(), 0
    for k, b in enumerate(out):
        if not isinstance(b, Figure) or b.caption:
            continue
        for j in (k + 1, k - 1):
            if 0 <= j < len(out) and j not in taken and isinstance(out[j], Caption) and not out[j].slot:
                out[k] = b.model_copy(update={"caption": out[j].text})
                taken.add(j)
                n += 1
                break
    return out, n
