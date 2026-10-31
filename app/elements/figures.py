# the figure element: a picture cut from its page by the box an engine drew, and whether the bundle holds it as a file
import re
from collections.abc import Callable

from document.model import Caption, Figure, PageMarker, Piece


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


REACH = 2


def _free(out: list, j: int, taken: set[int]) -> bool:
    return 0 <= j < len(out) and j not in taken and isinstance(out[j], Caption) and not out[j].slot


# no other figure and no page break stands between a figure and a caption two blocks off
def _clear(out: list, k: int, j: int) -> bool:
    return not any(isinstance(b, Figure | PageMarker) for b in out[min(k, j) + 1:max(k, j)])


# the side a piece sets its captions on, from figures with a caption on one side only; after the picture by default
def _side(out: list) -> int:
    sides = [1 if after else -1 for k, b in enumerate(out) if isinstance(b, Figure)
             if (after := _free(out, k + 1, set())) != _free(out, k - 1, set())]
    return -1 if sides.count(-1) > sides.count(1) else 1


# a caption block by a figure, on the piece's own side first and within two blocks as a series reaches, is its own
def captioned(blocks: list) -> tuple[list, int]:
    out, taken, n = list(blocks), set(), 0
    side = _side(out)
    for k, b in enumerate(out):
        if not isinstance(b, Figure) or b.caption:
            continue
        near = [k + side, k - side, k + REACH * side, k - REACH * side]
        if (j := next((j for j in near if _free(out, j, taken) and _clear(out, k, j)), None)) is not None:
            out[k] = b.model_copy(update={"caption": out[j].text})
            taken.add(j)
            n += 1
    return out, n
