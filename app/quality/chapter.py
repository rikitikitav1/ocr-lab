# a chapter's checks as numbers, read from the assembled chapter and the book's own text layer, never from a gold
import re
from bisect import bisect_left
from collections import Counter
from functools import cache

import settings
import wordfreq
import yaml
from assembly.passes import same_title
from assembly.referee import WORD, block_text
from document.model import Chapter, Figure, Heading, PageMarker, Paragraph
from stages import running_heads
from writers import markdown


@cache
def conf() -> dict:
    return yaml.safe_load((settings.CONFIG_DIR / "quality.yaml").read_text())["chapter"]


def _words(text: str) -> Counter:
    return Counter(WORD.findall(text.lower()))


def _pages(chapter: Chapter) -> dict[int, list]:
    out: dict[int, list] = {}
    page = None
    for b in chapter.blocks:
        if isinstance(b, PageMarker):
            page = b.book_page
            out.setdefault(page, [])
        elif page is not None:
            out[page].append(b)
    return out


# word agreement with the layer only on pages that have one, so a cover's picture neither helps nor hurts
def _layer(chapter: Chapter, layer: dict[int, str], furniture: dict[str, list[str]], min_words: int,
           shared: frozenset[int] = frozenset()) -> dict:
    pages = _pages(chapter)
    text_pages = [p for p, t in layer.items() if sum(_words(t).values()) >= min_words and p not in shared]
    want, got = Counter(), Counter()
    for p in text_pages:
        want += _words(layer[p])
        got += _words(" ".join(block_text(b) for b in pages.get(p, [])))
    # the writer puts the chapter's title above its blocks; a shared first page counts it in _shared instead
    got += _words(chapter.title) if text_pages and not _title_shared(chapter, layer, min_words, shared) else Counter()
    # only the layer's own heads and folios are subtracted, so a block an engine wrongly set aside counts as lost
    heads = _words(" ".join(furniture.get("layer", [])))
    want -= heads
    if not text_pages:
        return {"layer_pages": 0, "layer_words": 0, "lost_words": 0, "extra_words": 0, "lost_text": None,
                "extra_text": None, "set_aside_words": 0}
    common = sum((want & got).values())
    lost, extra = sum(want.values()) - common, sum(got.values()) - common
    set_aside = (_set_aside({k: v for k, v in furniture.items() if k != "layer"}) - heads) & (want - got)
    return {"layer_pages": len(text_pages), "layer_words": sum(want.values()), "lost_words": lost,
            "extra_words": extra, "set_aside_words": sum(set_aside.values()),
            "lost_text": round(lost / max(1, sum(want.values())), 3),
            "extra_text": round(extra / max(1, sum(got.values())), 3)}


def _set_aside(furniture: dict[str, list[str]]) -> Counter:
    out = Counter()
    for texts in furniture.values():
        out |= _words(" ".join(texts))
    return out


# heading levels as the chapter's Markdown writes them, code fences skipped: the chapter's own, then the rest
def _written_levels(text: str) -> tuple[int, list[int]]:
    levels, fenced = [], False
    for line in text.split("\n"):
        if line.startswith("```"):
            fenced = not fenced
        elif not fenced and (m := re.match(r"(#{1,6}) ", line)):
            levels.append(len(m[1]))
    return (levels[0], levels[1:]) if levels else (0, [])


def _structure(chapter: Chapter, subs: list[tuple[str, int]]) -> dict:
    heads = [b.text for b in chapter.blocks if isinstance(b, Heading)]
    title_level, levels = _written_levels(markdown.chapter(chapter))
    missing = [title for title, _ in subs if not any(same_title(h, title) for h in heads)]
    return {"pages": chapter.last_page - chapter.first_page + 1, "subs": len(subs),
            "subs_found": len(subs) - len(missing), "subs_missing": missing[:10], "headings": len(heads),
            "long_headings": sum(len(h.split()) > conf()["heading_max_words"] for h in heads),
            "empty_headings": sum(not h.strip() for h in heads), "title_level": title_level,
            "max_heading_level": max([title_level, *levels]),
            "headings_not_below_title": sum(level <= title_level for level in levels),
            "heading_sources": dict(Counter(b.level_source for b in chapter.blocks if isinstance(b, Heading)))}


def _figures(chapter: Chapter) -> dict:
    figures = [b for b in chapter.blocks if isinstance(b, Figure)]
    return {"figures": len(figures), "figures_not_kept": sum(not markdown.image_kept(b.image) for b in figures)}


# recognised pages are measured by how far the two engines agree, since they have no layer to compare with
def _recognised(agreement: dict[int, float]) -> dict:
    if not agreement:
        return {"recognised_pages": 0, "agreement": None, "agreement_min": None}
    return {"recognised_pages": len(agreement), "agreement": round(sum(agreement.values()) / len(agreement), 3),
            "agreement_min": min(agreement.values())}


# the book's running heads and bare folios left in the text as paragraphs; a heading is often its page's head too
def _heads_in_text(chapter: Chapter, furniture: dict[str, list[str]]) -> dict:
    lines = furniture.get("layer", [])
    heads = {key for h in lines if (key := running_heads.edge_key(h))}
    folios = {m[1] for h in lines if (m := running_heads.FOLIO.fullmatch(h))}
    def left(text: str) -> bool:
        folio = running_heads.FOLIO.fullmatch(text)
        return running_heads.edge_key(text) in heads or bool(folio and folio[1] in folios)

    found = sum(isinstance(b, Paragraph) and left(b.text) for b in chapter.blocks)
    return {"running_heads_in_text": found}


# languages wordfreq cannot split without a segmenter; their share stays unknown rather than wrong
SPACELESS = {"zh", "ja", "ko", "th"}


# on recognised pages: the share of words a dictionary of the book's languages knows, a measure needing no gold
def _dictionary(chapter: Chapter, recognised: dict[int, float], languages: list[str]) -> dict:
    # a language spaceless or missing from wordfreq leaves its words unknown yet counted, so the share would mislead
    unseen = SPACELESS & set(languages) or set(languages) - set(wordfreq.available_languages())
    langs = [] if unseen else languages
    pages = _pages(chapter)
    words = [w.lower() for p in recognised for b in pages.get(p, [])
             for w in re.findall(r"[^\W\d_]{2,}", block_text(b))]
    if not words or not langs:
        return {"dictionary_words": len(words), "dictionary_share": None}
    known = sum(any(wordfreq.zipf_frequency(w, lang) > 0 for lang in langs) for w in words)
    return {"dictionary_words": len(words), "dictionary_share": round(known / len(words), 3)}


# words written from pages without a layer, which extra_text cannot see: a cover's OCR'd thumbnails
def _layerless(chapter: Chapter, layer: dict[int, str], min_words: int) -> dict:
    checked = {p for p, t in layer.items() if sum(_words(t).values()) >= min_words}
    return {"layerless_words": sum(sum(_words(block_text(b)).values()) for p, blocks in _pages(chapter).items()
                                   if p not in checked for b in blocks)}


# a paragraph met again inside one chapter: text an engine or a merge wrote twice
def _repeated(chapter: Chapter) -> dict:
    seen = Counter(" ".join(b.text.split()) for b in chapter.blocks if isinstance(b, Paragraph))
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


# word runs met once in the layer and once in the chapter are anchors; those off the longest in-order run moved
def _order(chapter: Chapter, layer: dict[int, str], min_words: int) -> dict:
    pages = _pages(chapter)
    text_pages = sorted(p for p, t in layer.items() if sum(_words(t).values()) >= min_words)
    n = conf()["order_run_words"]
    want = _grams([w for p in text_pages for w in WORD.findall(layer[p].lower())], n)
    got = _grams([w for p in text_pages for b in pages.get(p, []) for w in WORD.findall(block_text(b).lower())], n)
    anchors = [got[g] for g in sorted(set(want) & set(got), key=want.get)]
    moved = len(anchors) - _longest_rising(anchors)
    return {"order_anchors": len(anchors), "out_of_order_anchors": moved,
            "out_of_order": round(moved / len(anchors), 3) if anchors else None}


def _title_shared(chapter: Chapter, layer: dict[int, str], min_words: int, shared: frozenset[int]) -> bool:
    page = chapter.first_page
    return page in shared and page in layer and sum(_words(layer[page]).values()) >= min_words


# a page two chapters share is measured by the book over all its chapters, so each gives its words on it
def _shared(chapter: Chapter, layer: dict[int, str], furniture: dict[str, list[str]], min_words: int,
            shared: frozenset[int]) -> dict:
    pages, heads = _pages(chapter), _words(" ".join(furniture.get("layer", [])))
    out = {}
    for p in sorted(shared):
        if p in layer and sum(_words(layer[p]).values()) >= min_words:
            got = _words(" ".join(block_text(b) for b in pages.get(p, [])))
            # the writer sets the chapter's title on top, and the title stands on its first page
            got += _words(chapter.title) if p == chapter.first_page else Counter()
            out[str(p)] = {"layer": dict(_words(layer[p]) - heads), "got": dict(got)}
    return {"shared_pages": out}


def check(chapter: Chapter, subs: list[tuple[str, int]], layer: dict[int, str],
          furniture: dict[str, list[str]] | None = None, recognised: dict[int, float] | None = None,
          shared: frozenset[int] = frozenset(), languages: list[str] | None = None) -> dict:
    min_words = conf()["layer_min_words"]
    return {**_layer(chapter, layer, furniture or {}, min_words, shared),
            **_shared(chapter, layer, furniture or {}, min_words, shared), **_structure(chapter, subs),
            **_figures(chapter), **_recognised(recognised or {}),
            **_layerless(chapter, layer, min_words), **_repeated(chapter), **_order(chapter, layer, min_words),
            **_heads_in_text(chapter, furniture or {}), **_dictionary(chapter, recognised or {}, languages or [])}
