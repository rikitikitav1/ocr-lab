# the book's numbers: totals over its chapters, whole-book checks, and the worst chapters by each number
import re
from collections import Counter, defaultdict

import settings
import yaml

FENCE = re.compile(r"^(`{3,}|~{3,}).*?^\1[ \t]*$", re.M | re.S)


def conf() -> dict:
    return yaml.safe_load((settings.CONFIG_DIR / "quality.yaml").read_text())["book"]


# code is left out: a listing repeated on purpose (a full program after its parts) is not a page taken twice
def duplicates(texts: dict[int, str]) -> list[dict]:
    seen: dict[str, set[int]] = defaultdict(set)
    for ord, text in texts.items():
        for para in FENCE.sub("", text).split("\n\n"):
            key = " ".join(para.split())
            if len(key) >= conf()["duplicate_min_chars"] and not key.startswith("<!--"):
                seen[key].add(ord)
    return [{"chapters": sorted(ords), "text": key[:80]} for key, ords in seen.items() if len(ords) > 1]


def _share(part: int, whole: int) -> float | None:
    return round(part / whole, 3) if whole else None


# a shared page's layer against the words all its chapters wrote on it, as (lost, extra, layer words)
def shared_words(checks: list[dict]) -> tuple[int, int, int]:
    layer: dict[str, Counter] = {}
    got: dict[str, Counter] = defaultdict(Counter)
    for k in checks:
        for page, words in (k.get("shared_pages") or {}).items():
            layer[page] = Counter(words["layer"])
            got[page] += Counter(words["got"])
    want = sum(layer.values(), Counter())
    have = sum((got[p] for p in layer), Counter())
    common = sum((want & have).values())
    return sum(want.values()) - common, sum(have.values()) - common, sum(want.values())


# a chapter's sections and their sub-sections are usual, so only headings deeper than that make it a deep one
def _past_subsections(chapter: dict) -> bool:
    checks = chapter["checks"] or {}
    return (checks.get("max_heading_level") or 0) - (checks.get("title_level") or 2) > 2


# chapters are dicts of ord, title, status and checks
def numbers(chapters: list[dict], doubled: list[dict]) -> dict:
    done = [c for c in chapters if c["status"] == "done"]
    checks = [c["checks"] or {} for c in done]

    def total(key: str) -> int:
        return sum(k.get(key) or 0 for k in checks)

    def worst(key: str, among: list[dict] = done) -> list[dict]:
        rated = sorted((c for c in among if (c["checks"] or {}).get(key)), key=lambda c: -c["checks"][key])
        return [{"ord": c["ord"], "title": c["title"], key: c["checks"][key]}
                for c in rated[:conf()["worst_chapters"]]]

    shared_lost, shared_extra, shared_layer = shared_words(checks)
    lost, extra, layer = total("lost_words") + shared_lost, total("extra_words") + shared_extra, \
        total("layer_words") + shared_layer
    recognised = total("recognised_pages")
    agreed = sum((k.get("agreement") or 0) * (k.get("recognised_pages") or 0) for k in checks)
    return {"chapters": len(chapters), "chapters_done": len(done),
            "chapters_failed": [c["ord"] for c in chapters if c["status"] != "done"],
            "lost_text": _share(lost, layer), "extra_text": _share(extra, layer - lost + extra),
            "set_aside_words": total("set_aside_words"),
            "layer_pages": total("layer_pages"), "subs": total("subs"), "subs_found": total("subs_found"),
            "long_headings": total("long_headings"), "empty_headings": total("empty_headings"),
            "max_heading_level": max((k.get("max_heading_level") or 0 for k in checks), default=0),
            "heading_sources": dict(sum((Counter(k.get("heading_sources") or {}) for k in checks), Counter())),
            "chapters_below_sections": [c["ord"] for c in done if (c["checks"] or {}).get("headings_not_below_title")],
            "duplicates": len(doubled), "repeated_paragraphs": total("repeated_paragraphs"),
            "running_heads_in_text": total("running_heads_in_text"),
            "out_of_order": _share(total("out_of_order_anchors"), total("order_anchors")),
            "layerless_words": total("layerless_words"),
            "picture_pages": sum((k.get("passes") or {}).get("pages_picture", 0) for k in checks),
            "recognised_pages": recognised, "agreement": round(agreed / recognised, 3) if recognised else None,
            "dictionary_share": _share(round(sum((k.get("dictionary_share") or 0) * (k.get("dictionary_words") or 0)
                                                 for k in checks if k.get("dictionary_share") is not None)),
                                       sum(k.get("dictionary_words") or 0 for k in checks
                                           if k.get("dictionary_share") is not None)),
            "worst": {"lost_text": worst("lost_text"), "extra_text": worst("extra_text"),
                      "out_of_order": worst("out_of_order"),
                      "max_heading_level": worst("max_heading_level", [c for c in done if _past_subsections(c)]),
                      "repeated_paragraphs": worst("repeated_paragraphs"), "long_headings": worst("long_headings"),
                      "agreement": [{"ord": c["ord"], "title": c["title"], "agreement": c["checks"]["agreement"]}
                                    for c in sorted((c for c in done if (c["checks"] or {}).get("agreement")
                                                     is not None), key=lambda c: c["checks"]["agreement"])]
                      [:conf()["worst_chapters"]],
                      "subs_missing": [{"ord": c["ord"], "title": c["title"],
                                        "missing": c["checks"]["subs"] - c["checks"]["subs_found"]}
                                       for c in sorted(done, key=lambda c: -((c["checks"] or {}).get("subs", 0)
                                                                            - (c["checks"] or {}).get("subs_found", 0)))
                                       if c["checks"].get("subs", 0) > c["checks"].get("subs_found", 0)]
                      [:conf()["worst_chapters"]]}}
