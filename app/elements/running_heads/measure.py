# the running head element measured: heads and folios left in a piece's text
from document.model import Heading, Paragraph, Piece
from document.text import WORD

from elements.running_heads.book import FOLIO, edge_key


# running heads and folios left as a paragraph or an unpinned heading (a node's title is often its head), or glued
def in_text(piece: Piece, furniture: dict[str, list[str]]) -> dict:
    lines = furniture.get("layer", [])
    heads = {key for h in lines if (key := edge_key(h))}
    folios = {m[1] for h in lines if (m := FOLIO.fullmatch(h))}
    def left(text: str) -> bool:
        folio = FOLIO.fullmatch(text)
        return edge_key(text) in heads or bool(folio and folio[1] in folios)

    phrases = {p for h in lines if len(p := tuple(_head_words(h))) >= GLUED_WORDS}
    def glued(text: str) -> bool:
        got = tuple(WORD.findall(text.lower()))
        return any(len(got) > len(p) and (got[:len(p)] == p or got[-len(p):] == p) for p in phrases)

    alone = sum((isinstance(b, Paragraph) or isinstance(b, Heading) and b.node is None) and left(b.text)
                for b in piece.blocks)
    return {"running_heads_in_text": alone,
            "running_heads_glued": sum(isinstance(b, Paragraph) and glued(b.text) for b in piece.blocks)}


GLUED_WORDS = 2


# a running head's words without the folio at either end
def _head_words(line: str) -> list[str]:
    words = WORD.findall(line.lower())
    while words and words[0].isdigit():
        words = words[1:]
    while words and words[-1].isdigit():
        words = words[:-1]
    return words
