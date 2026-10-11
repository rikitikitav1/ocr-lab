# one toc from all sources: a base, the others voting and adding what it lacks; printed contents first
from collections import Counter

from rapidfuzz import fuzz

from stages.toc.pages import LABEL, label_of, norm, same_words
from stages.toc.sources import Entry

RANK = ("printed_contents", "bookmarks", "files", "numbering")
# numbering in running text also hits references and lists, so alone it adds only a labelled part or chapter
VOTES_ONLY = ("numbering",)
MIN_ENTRIES = 2
SAME_TITLE = 88
SAME_PAGE = 1
NEAR_PAGE = 15


def bare(title: str) -> str:
    return norm(LABEL.sub("", title.strip(), count=1)) or norm(title)


def _same(a: Entry, b: Entry) -> bool:
    if abs(a.page - b.page) > NEAR_PAGE:
        return False
    x, y = bare(a.title), bare(b.title)
    if x and y and fuzz.ratio(x, y) >= SAME_TITLE:
        return True
    return abs(a.page - b.page) <= SAME_PAGE and (same_words(a.title, b.title) or label_of(a.title, b.title)
                                                  or label_of(b.title, a.title))


def _vote(entry: Entry) -> dict:
    return {"level": entry.level, "page": entry.page, "printed": entry.printed, "evidence": entry.evidence}


def _placed(entries: list[Entry]) -> list[Entry]:
    return [e for e in entries if e.page is not None]


def _top(entries: list[Entry]) -> int:
    return min((e.level or 1 for e in entries), default=1)


def _trusted(entries: list[Entry]) -> bool:
    placed = _placed(entries)
    return len(placed) >= MIN_ENTRIES and sum(e.verified for e in placed) * 2 > len(placed)


def reconcile(found: dict[str, list[Entry]]) -> tuple[str | None, list[Entry], dict]:
    present = [s for s in RANK if len(_placed(found.get(s, []))) >= MIN_ENTRIES]
    base = next((s for s in present if s not in VOTES_ONLY and _trusted(found[s])), None)
    base = base or next((s for s in present if s not in VOTES_ONLY), None)
    if base is None:
        return None, [], {"sources": present}
    merged = []
    for e in _placed(found[base]):
        merged.append(Entry(e.title, e.level, e.page, e.printed, e.evidence, e.verified, base, {base: _vote(e)}))
    base_top = _top(merged)
    report = {"base": base, "matched": {}, "conflicts": [], "added": []}
    unmatched: list[tuple[str, Entry, int]] = []
    for source in present:
        if source == base:
            continue
        entries = _placed(found[source])
        top = _top(entries)
        report["matched"][source] = 0
        for e in entries:
            match = next((m for m in merged if source not in m.votes and _same(m, e)), None)
            if match is None:
                unmatched.append((source, e, top))
                continue
            match.votes[source] = _vote(e)
            report["matched"][source] += 1
            if abs(match.page - e.page) > SAME_PAGE:
                report["conflicts"].append({"title": match.title, base: match.page, source: e.page})
    _add_missing(merged, unmatched, base_top, report)
    _levels_from_bookmarks(merged, report)
    order = {id(e): i for i, e in enumerate(merged)}
    merged.sort(key=lambda e: (e.page, order[id(e)]))
    return base, merged, report


# titles and pages from the base, levels from bookmarks where matched, the rest moved onto their scale
def _levels_from_bookmarks(merged: list[Entry], report: dict) -> None:
    paired: dict[tuple[str, int], Counter] = {}
    for e in merged:
        mark = e.votes.get("bookmarks")
        if mark and e.source != "bookmarks" and e.level is not None:
            paired.setdefault((e.source, e.level), Counter())[mark["level"]] += 1
    if not paired:
        return
    scale = {key: counts.most_common(1)[0][0] for key, counts in paired.items()}
    moved = 0
    for e in merged:
        mark = e.votes.get("bookmarks")
        if mark:
            new = mark["level"]
        elif e.level is None:
            continue
        else:
            known = [lvl for (source, lvl) in scale if source == e.source]
            if not known:
                continue
            nearest = min(known, key=lambda lvl: abs(lvl - e.level))
            new = scale[(e.source, nearest)] + e.level - nearest
        if new != e.level:
            moved += 1
        e.level, e.source = max(new, 1), "bookmarks" if mark else e.source
    report["levels_from_bookmarks"] = {"scale": {f"{s}:{lvl}": v for (s, lvl), v in scale.items()}, "moved": moved}


# a missing entry comes in when two other sources have it, or it is a top entry on a confirmed page
def _add_missing(merged: list[Entry], unmatched: list[tuple[str, Entry, int]], base_top: int, report: dict) -> None:
    taken = set()
    for i, (source, e, top) in enumerate(unmatched):
        if i in taken or (source in VOTES_ONLY and not e.evidence.startswith("labelled ")):
            continue
        partners = [j for j, (other, x, _) in enumerate(unmatched)
                    if j != i and j not in taken and other != source and _same(e, x)]
        if not partners and not (e.verified and (e.level or top) == top):
            continue
        level = min((e.level or top) - top + base_top, 6)
        entry = Entry(e.title, level, e.page, e.printed, e.evidence, e.verified, source, {source: _vote(e)})
        for j in partners:
            entry.votes[unmatched[j][0]] = _vote(unmatched[j][1])
            taken.add(j)
        taken.add(i)
        merged.append(entry)
        report["added"].append({"title": e.title, "page": e.page, "from": sorted(entry.votes)})
