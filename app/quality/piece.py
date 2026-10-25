# a piece's checks as numbers, read from the assembled piece and the book's own text layer, never from a gold
import re
from bisect import bisect_left
from collections import Counter
from functools import cache

import settings
import wordfreq
import yaml
from assembly.passes import same_title
from assembly.referee import WORD, block_text
from document.model import Caption, Heading, PageMarker, Paragraph, Piece
from elements import figures, running_heads
from elements.code import listing_numbers
from writers import markdown


@cache
def conf() -> dict:
    return yaml.safe_load((settings.CONFIG_DIR / "quality.yaml").read_text())["piece"]


def words(text: str) -> Counter:
    return Counter(WORD.findall(text.lower()))


def _pages(piece: Piece) -> dict[int, list]:
    out: dict[int, list] = {}
    page = None
    for b in piece.blocks:
        if isinstance(b, PageMarker):
            page = b.book_page
            out.setdefault(page, [])
        elif page is not None:
            out[page].append(b)
    return out


# word agreement with the layer only on pages that have one, so a cover's picture neither helps nor hurts
def _layer(piece: Piece, layer: dict[int, str], furniture: dict[str, list[str]], min_words: int,
           shared: frozenset[int] = frozenset()) -> dict:
    pages = _pages(piece)
    text_pages = [p for p, t in layer.items() if sum(words(t).values()) >= min_words and p not in shared]
    want, got = Counter(), Counter()
    for p in text_pages:
        want += words(layer[p])
        got += words(" ".join(block_text(b) for b in pages.get(p, [])))
    # the writer puts the piece's title above its blocks; a shared first page counts it in _shared instead
    got += words(piece.title) if text_pages and not _title_shared(piece, layer, min_words, shared) else Counter()
    # only the layer's own heads and folios are subtracted, so a block an engine wrongly set aside counts as lost
    heads = words(" ".join(furniture.get("layer", [])))
    want -= heads
    if not text_pages:
        return {"layer_pages": 0, "layer_words": 0, "lost_words": 0, "extra_words": 0, "lost_text": None,
                "extra_text": None, "set_aside_words": 0, "listing_numbers": 0, "lost_words_no_listing": 0}
    common = sum((want & got).values())
    lost, extra = sum(want.values()) - common, sum(got.values()) - common
    set_aside = (_set_aside({k: v for k, v in furniture.items() if k != "layer"}) - heads) & (want - got)
    listing = sum((listing_numbers(layer[p]) for p in text_pages), Counter())
    return {"layer_pages": len(text_pages), "layer_words": sum(want.values()), "lost_words": lost,
            "extra_words": extra, "set_aside_words": sum(set_aside.values()),
            "listing_numbers": sum(listing.values()),
            "lost_words_no_listing": lost - sum((listing & (want - got)).values()),
            "lost_text": round(lost / max(1, sum(want.values())), 3),
            "extra_text": round(extra / max(1, sum(got.values())), 3)}


def _set_aside(furniture: dict[str, list[str]]) -> Counter:
    out = Counter()
    for texts in furniture.values():
        out |= words(" ".join(texts))
    return out


# heading levels as the piece's Markdown writes them, code fences skipped: the piece's own, then the rest
def _written_levels(text: str) -> tuple[int, list[int]]:
    levels, fenced = [], False
    for line in text.split("\n"):
        if line.startswith("```"):
            fenced = not fenced
        elif not fenced and (m := re.match(r"(#{1,6}) ", line)):
            levels.append(len(m[1]))
    return (levels[0], levels[1:]) if levels else (0, [])


def _structure(piece: Piece, subs: list[tuple[str, int]]) -> dict:
    heads = [b.text for b in piece.blocks if isinstance(b, Heading)]
    title_level, levels = _written_levels(markdown.piece(piece))
    # the pins decide what was found, one heading per entry, so this count and the tree's pinned count agree
    if piece.nodes:
        missing = [n.title for n in piece.nodes[1:] if not n.pinned]
    else:
        missing = [title for title, _ in subs if not any(same_title(h, title) for h in heads)]
    # nodes whose headings stand in another order than the structure's: those off the longest run in node order
    anchors = [b.node for b in piece.blocks if isinstance(b, Heading) and b.node is not None]
    return {"pages": piece.last_page - piece.first_page + 1, "subs": len(subs),
            "nodes_out_of_order": len(anchors) - _longest_rising(anchors),
            "subs_found": len(subs) - len(missing), "subs_missing": missing[:10], "headings": len(heads),
            "long_headings": sum(len(h.split()) > conf()["heading_max_words"] for h in heads),
            "empty_headings": sum(not h.strip() for h in heads), "title_level": title_level,
            "max_heading_level": max([title_level, *levels]),
            "headings_not_below_title": sum(level <= title_level for level in levels),
            "heading_sources": dict(Counter(b.level_source for b in piece.blocks if isinstance(b, Heading)))}


CAPTION_FOUND = 0.6
CAPTION_KINDS = {Caption: "caption", Paragraph: "paragraph", Heading: "heading"}


# where each caption the layer sets by a picture went: the block on its page holding most of its words, or lost
def _captions(piece: Piece, captions: dict[int, list[str]]) -> dict:
    out = {"captions": 0, **{f"captions_in_{k}": 0 for k in CAPTION_KINDS.values()}, "captions_lost": 0}
    pages = _pages(piece)
    for page, texts in captions.items():
        blocks = [b for b in pages.get(page, []) if type(b) in CAPTION_KINDS]
        for text in texts:
            want = words(text)
            if not want:
                continue
            share, kind = max(((sum((want & words(block_text(b))).values()) / sum(want.values()),
                                CAPTION_KINDS[type(b)]) for b in blocks), default=(0.0, None))
            out["captions"] += 1
            out[f"captions_in_{kind}" if share >= CAPTION_FOUND else "captions_lost"] += 1
    return out


# recognised pages are measured by how far the two engines agree, since they have no layer to compare with
def _recognised(agreement: dict[int, float]) -> dict:
    if not agreement:
        return {"recognised_pages": 0, "agreement": None, "agreement_min": None}
    return {"recognised_pages": len(agreement), "agreement": round(sum(agreement.values()) / len(agreement), 3),
            "agreement_min": min(agreement.values())}


# languages wordfreq cannot split without a segmenter; their share stays unknown rather than wrong
SPACELESS = {"zh", "ja", "ko", "th"}


# on recognised pages: the share of words a dictionary of the book's languages knows, a measure needing no gold
def _dictionary(piece: Piece, recognised: dict[int, float], languages: list[str]) -> dict:
    pages = _pages(piece)
    words = dictionary_words(" ".join(block_text(b) for p in recognised for b in pages.get(p, [])))
    return {"dictionary_words": len(words), "dictionary_share": dictionary_share(words, languages)}


def dictionary_words(text: str) -> list[str]:
    return [w.lower() for w in re.findall(r"[^\W\d_]{2,}", text)]


def dictionary_share(words: list[str], languages: list[str]) -> float | None:
    # a language spaceless or missing from wordfreq leaves its words unknown yet counted, so the share would mislead
    unseen = SPACELESS & set(languages) or set(languages) - set(wordfreq.available_languages())
    if not words or unseen or not languages:
        return None
    known = sum(any(wordfreq.zipf_frequency(w, lang) > 0 for lang in languages) for w in words)
    return round(known / len(words), 3)


# words written from pages without a layer, which extra_text cannot see: a cover's OCR'd thumbnails
def _layerless(piece: Piece, layer: dict[int, str], min_words: int) -> dict:
    checked = {p for p, t in layer.items() if sum(words(t).values()) >= min_words}
    return {"layerless_words": sum(sum(words(block_text(b)).values()) for p, blocks in _pages(piece).items()
                                   if p not in checked for b in blocks)}


# a paragraph met again inside one piece: text an engine or a merge wrote twice
def _repeated(piece: Piece) -> dict:
    seen = Counter(" ".join(b.text.split()) for b in piece.blocks if isinstance(b, Paragraph))
    return {"repeated_paragraphs": sum(n - 1 for key, n in seen.items()
                                       if n > 1 and len(key) >= conf()["repeated_min_chars"])}


def _grams(words: list[str], n: int) -> dict[tuple, int]:
    runs = [tuple(words[i:i + n]) for i in range(len(words) - n + 1)]
    counts = Counter(runs)
    return {run: i for i, run in enumerate(runs) if counts[run] == 1}


def _longest_rising(values: list[int]) -> int:
    tails: list[int] = []
    for v in values:
        i = bisect_left(tails, v)
        tails[i:i + 1] = [v]
    return len(tails)


# word runs met once in the layer and once in the piece are anchors; those off the longest in-order run moved
def _order(piece: Piece, layer: dict[int, str], min_words: int) -> dict:
    pages = _pages(piece)
    text_pages = sorted(p for p, t in layer.items() if sum(words(t).values()) >= min_words)
    n = conf()["order_run_words"]
    want = _grams([w for p in text_pages for w in WORD.findall(layer[p].lower())], n)
    got = _grams([w for p in text_pages for b in pages.get(p, []) for w in WORD.findall(block_text(b).lower())], n)
    anchors = [got[g] for g in sorted(set(want) & set(got), key=want.get)]
    moved = len(anchors) - _longest_rising(anchors)
    return {"order_anchors": len(anchors), "out_of_order_anchors": moved,
            "out_of_order": round(moved / len(anchors), 3) if anchors else None}


def _title_shared(piece: Piece, layer: dict[int, str], min_words: int, shared: frozenset[int]) -> bool:
    page = piece.first_page
    return page in shared and page in layer and sum(words(layer[page]).values()) >= min_words


# a page two pieces share is measured by the book over all its pieces, so each gives its words on it
def _shared(piece: Piece, layer: dict[int, str], furniture: dict[str, list[str]], min_words: int,
            shared: frozenset[int]) -> dict:
    pages, heads = _pages(piece), words(" ".join(furniture.get("layer", [])))
    out = {}
    for p in sorted(shared):
        if p in layer and sum(words(layer[p]).values()) >= min_words:
            got = words(" ".join(block_text(b) for b in pages.get(p, [])))
            # the writer sets the piece's title on top, and the title stands on its first page
            got += words(piece.title) if p == piece.first_page else Counter()
            out[str(p)] = {"layer": dict(words(layer[p]) - heads), "got": dict(got)}
    return {"shared_pages": out}


def check(piece: Piece, subs: list[tuple[str, int]], layer: dict[int, str],
          furniture: dict[str, list[str]] | None = None, recognised: dict[int, float] | None = None,
          shared: frozenset[int] = frozenset(), languages: list[str] | None = None,
          captions: dict[int, list[str]] | None = None) -> dict:
    min_words = conf()["layer_min_words"]
    return {**_layer(piece, layer, furniture or {}, min_words, shared),
            **_shared(piece, layer, furniture or {}, min_words, shared), **_structure(piece, subs),
            **figures.counts(piece), **_captions(piece, captions or {}), **_recognised(recognised or {}),
            **_layerless(piece, layer, min_words), **_repeated(piece), **_order(piece, layer, min_words),
            **running_heads.in_text(piece, furniture or {}), **_dictionary(piece, recognised or {}, languages or [])}
