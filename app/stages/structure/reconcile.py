# one structure from all sources: a base, the others voting and adding what it lacks; printed contents first
import re
from collections import Counter

from rapidfuzz import fuzz

from stages.structure.pages import LABEL, label_of, norm, same_words
from stages.structure.sources import Entry

RANK = ("printed_contents", "bookmarks", "files", "text_headings", "numbering")
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
        entries = _joined(_placed(found[source]), merged)
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


def _squashed(title: str) -> str:
    return re.sub(r"\W", "", title.lower())


def _glued(parts: list[Entry]) -> Entry:
    title = parts[0].title.strip()
    for p in parts[1:]:
        title += p.title.strip() if title.endswith("-") else " " + p.title.strip()
    return Entry(title, parts[0].level, parts[0].page, parts[0].printed, parts[0].evidence,
                 any(p.verified for p in parts), parts[0].source)


def _fit(title: str, rows: list[str]) -> float:
    return max((fuzz.ratio(_squashed(title), r) for r in rows), default=0)


# a title split over entries of one page and level is one entry when only their join reads as a base row
def _joined(entries: list[Entry], base: list[Entry]) -> list[Entry]:
    out, i = [], 0
    while i < len(entries):
        run = [entries[i]]
        while i + len(run) < len(entries) and (entries[i + len(run)].page, entries[i + len(run)].level) == \
                (run[0].page, run[0].level):
            run.append(entries[i + len(run)])
        near = [_squashed(b.title) for b in base if abs(b.page - run[0].page) <= SAME_PAGE]
        best, best_fit = 1, _fit(run[0].title, near)
        if best_fit < SAME_TITLE:
            for k in range(2, len(run) + 1):
                if _fit(run[k - 1].title, near) >= SAME_TITLE:
                    break
                got = _fit(_glued(run[:k]).title, near)
                if got >= SAME_TITLE and got > best_fit:
                    best, best_fit = k, got
        out.append(_glued(run[:best]) if best > 1 else run[0])
        i += best
    return out


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
        level = (e.level or top) - top + base_top
        entry = Entry(e.title, level, e.page, e.printed, e.evidence, e.verified, source, {source: _vote(e)})
        for j in partners:
            entry.votes[unmatched[j][0]] = _vote(unmatched[j][1])
            taken.add(j)
        taken.add(i)
        merged.append(entry)
        report["added"].append({"title": e.title, "page": e.page, "from": sorted(entry.votes)})
