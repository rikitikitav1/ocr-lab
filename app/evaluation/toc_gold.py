# a toc scored against a gold one: chapters on the right page at any level first, then entries and levels

from rapidfuzz import fuzz
from stages.toc.pages import label_of, same_words
from stages.toc.reconcile import bare
from stages.toc.sources import Entry

SAME_TITLE = 85
PAGE_SLACK = 1


# one title holding the other's words (an author's name before it, "Part I . X") is the same chapter
def _same(a: Entry, b: Entry) -> bool:
    if a.page is None or b.page is None or abs(a.page - b.page) > PAGE_SLACK:
        return False
    return (
        fuzz.ratio(bare(a.title), bare(b.title)) >= SAME_TITLE
        or same_words(a.title, b.title)
        or label_of(a.title, b.title)
        or label_of(b.title, a.title)
    )


def top_entries(entries: list[Entry]) -> list[Entry]:
    top = min((e.level or 1 for e in entries), default=1)
    return [e for e in entries if (e.level or 1) == top]


def _nearest(entry: Entry, entries: list[Entry]) -> dict | None:
    best = max(entries, key=lambda e: fuzz.ratio(bare(e.title), bare(entry.title)), default=None)
    if best is None or fuzz.ratio(bare(best.title), bare(entry.title)) < SAME_TITLE:
        return None
    return {"title": best.title, "page": best.page, "level": best.level}


def _pairs(gold: list[Entry], got: list[Entry]) -> list[tuple[Entry, Entry]]:
    used, out = set(), []
    for g in gold:
        match = next((i for i, e in enumerate(got) if i not in used and _same(e, g)), None)
        if match is not None:
            used.add(match)
            out.append((g, got[match]))
    return out


# gold chapters up to the last contents page (cover, copyright, contents) are listed apart, not counted
def score(gold: list[Entry], got: list[Entry], contents_end: int | None = None, service: list[Entry] = ()) -> dict:
    chapters, got_chapters = top_entries(gold), top_entries(got)
    front = [c for c in chapters if contents_end is not None and c.page <= contents_end]
    chapters = [c for c in chapters if c not in front]
    missed = [c for c in chapters if not any(_same(t, c) for t in got)]
    below_top = [c for c in chapters if c not in missed and not any(_same(t, c) for t in got_chapters)]
    # a top entry the gold lists at any level is a chapter on the right page, so only one matching nothing is extra
    extra = [t for t in got_chapters if not any(_same(t, c) for c in gold)]
    pairs = _pairs(gold, got)
    gold_top = min((e.level or 1 for e in gold), default=1)
    got_top = min((e.level or 1 for e in got), default=1)
    same_level = sum((g.level or 1) - gold_top == (e.level or 1) - got_top for g, e in pairs)
    return {
        "chapters": len(chapters), "chapters_found": len(chapters) - len(missed),
        "chapters_below_top": len(below_top), "extra_chapters": len(extra),
        "extra_service": len([t for t in extra if any(t is x for x in service)]),
        "not_counted": [{"title": c.title, "page": c.page} for c in front],
        "entries": len(gold), "entries_got": len(got), "entries_matched": len(pairs),
        "recall": round(len(pairs) / len(gold), 3) if gold else None,
        "precision": round(len(pairs) / len(got), 3) if got else None,
        "level_agreement": round(same_level / len(pairs), 3) if pairs else None,
        "missed_chapters": [{"title": c.title, "page": c.page, "found_as": _nearest(c, got)} for c in missed],
        "extra_chapter_titles": [{"title": t.title, "page": t.page} for t in extra],
    }
