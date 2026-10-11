# both engines over rag-lab's converter_gold sections, read through our adapters, scored per element
import json
import re
from collections import Counter
from functools import cache
from pathlib import Path

import artifacts
import code_version
import job_queue
import pdf
import settings
from assembly import code_layer, passes
from document.model import Table
from engines import converter_tools, reading
from job_signals import Final
from knobs import registry
from writers import markdown

from evaluation import element_gold

ENGINES = settings.ENGINES
# the stand's own assembly over both engines' readings, scored like an engine
ASSEMBLED = "assembled"
REGIME = "text_pdf"
READ_CEILING = 900


def gold_dir() -> Path:
    return settings.SHELF_DIR / "gold"


def sections() -> list[dict]:
    return json.loads((gold_dir() / "sections.json").read_text())["sections"]


def _readings_dir() -> Path:
    return settings.DATA_DIR / "gold" / "converter_gold" / "readings"


# a reading is kept by the cut, the fields and the engine build, so a new image or request reads again
def _structure(engine: str, cut: Path, language: str, build: dict) -> dict:
    given = reading.fields(engine, REGIME, [language])
    key = artifacts.input_hash(cut=artifacts.sha256_file(cut), fields=given, build=build)
    kept = _readings_dir() / engine / f"{cut.stem}.{key[:16]}.json"
    if kept.exists():
        return converter_tools.kept_file(kept)
    structure = reading.read(engine, cut, 1, pdf.page_count(cut), given, READ_CEILING, build)
    artifacts.atomic_write(kept, structure)
    return structure


# the gold's boxes are points on the original book's pages; the cut starts at the section's first page
def _clips(entry: dict, cut: Path) -> list[tuple[int, tuple]]:
    sizes = pdf.page_sizes(cut)
    out = []
    for b in entry["boxes"]:
        page = b["page"] - entry["pages"][0] + 1
        width, height = sizes[page - 1]
        x0, y0, x1, y1 = b["clip"]
        out.append((page, (x0 / width, y0 / height, x1 / width, y1 / height)))
    return out


GOLD_IN_LAYER = 0.75
GOLD_IN_CLIPS = 0.6


# a gold whose words are mostly absent from its own cut belongs to another section of the same title
def gold_in_layer(gold_md: str, cut: Path) -> float:
    words = re.compile(r"\w+")
    gold = Counter(words.findall(element_gold.plain(gold_md).lower()))
    layer = Counter(words.findall(" ".join(pdf.page_texts(cut).values()).lower()))
    return round(sum((gold & layer).values()) / max(1, sum(gold.values())), 2)


def _assembled(cut: Path, language: str, builds: dict, knobs: dict) -> tuple[list, Counter, list, Counter]:
    reads = {e: reading.adapt(e, _structure(e, cut, language, builds[e])) for e in ENGINES}
    layer = {i + 1: t for i, t in pdf.page_texts(cut).items()}
    blocks, counts = passes.apply(reads, layer, cache(lambda page: pdf.page_glyphs(cut, page - 1)), ENGINES,
                                  knobs=knobs)
    counts = Counter(counts)
    # the assembled reading's furniture and unknown labels are both engines' together
    return (blocks, counts, reads["docling"].furniture + reads["mineru"].furniture,
            reads["docling"].unknown + reads["mineru"].unknown)


def _member(engine: str, entry: dict, build, knobs: dict) -> dict:
    cut = gold_dir() / "files" / "sections" / f"{entry['id']}.pdf"
    gold_md = (gold_dir() / "files" / "gold_md" / f"{entry['id']}.md").read_text()
    picks = None
    if engine == ASSEMBLED:
        all_blocks, picks, furniture, unknown = _assembled(cut, entry["lang"], build, knobs)
    else:
        read = reading.adapt(engine, _structure(engine, cut, entry["lang"], build))
        all_blocks, furniture, unknown = read.blocks, read.furniture, read.unknown
    blocks, unplaced = element_gold.section(all_blocks, _clips(entry, cut))
    got_md = markdown.body(blocks, 1)
    running = element_gold.running_lines(pdf.page_lines(cut))
    marks = _marks(blocks, cut)
    return {"id": entry["id"], "doc": entry["doc"], "lang": entry["lang"], "kind": entry["kind"], "engine": engine,
            "unplaced": unplaced, "furniture": len(furniture), "unknown": dict(unknown),
            "picks": dict(picks) if picks is not None else None,
            "blocks": dict(Counter(b.type for b in blocks)),
            **marks, **element_gold.score(gold_md, got_md, blocks, running)}


# marks inside each table, in the layer and in the grid: the gold drops check marks, the layer keeps them
def _marks(blocks: list, cut: Path) -> dict:
    layer = out = 0
    for b in blocks:
        if isinstance(b, Table) and b.where is not None:
            page = pdf.page_glyphs(cut, b.where.page - 1)
            layer += sum(passes.is_mark(g[4]) for g in page if code_layer.inside(g, b.where.box))
            out += sum(passes.is_mark(ch) for row in b.rows for c in row for ch in c.text)
    return {"cells_marks_layer": layer, "cells_marks_out": out}


SUMMED = ("code", "code_exact", "code_contained", "code_out", "code_out_foreign", "code_out_merged", "cells",
          "cells_found", "table_rows", "table_rows_exact", "cells_broken_hyphen", "cells_marks_layer",
          "cells_marks_out",
          "cells_out", "headings", "headings_found", "headings_phantom", "running_leaked", "furniture",
          "figures_gold", "figures_out", "formulas_gold", "formulas_out")


def _totals(rows: list[dict]) -> dict:
    out = {k: sum(r[k] for r in rows) for k in SUMMED}
    out["sections"] = len(rows)
    out["unplaced"] = sum(r["unplaced"] for r in rows)
    out["similarity_mean"] = round(sum(r["similarity"] for r in rows) / len(rows), 1) if rows else None
    out["body_f1_mean"] = round(sum(r["body_f1"] for r in rows) / len(rows), 3) if rows else None
    out["unknown"] = dict(sum((Counter(r["unknown"]) for r in rows), Counter()))
    return out


# a cancel is read between sections; the rows land beside the readings, the totals in the job's result
def run(engines: list[str], ids: list[str] | None, job_id: int | None, knobs: dict | None = None) -> dict:
    passes_on = {path.removeprefix(registry.RUN_PREFIX): value for path, value in (knobs or {}).items()}
    chosen = [s for s in sections() if not ids or s["id"] in ids]
    if not chosen:
        raise Final(f"no converter_gold sections among {ids}")
    # a section rag-lab drew but could not give its own gold to is listed, not scored
    no_gold, mismatch, gold_checks = [], [], {}
    for s in chosen:
        gold = gold_dir() / "files" / "gold_md" / f"{s['id']}.md"
        if not gold.exists():
            no_gold.append(s["id"])
            continue
        cut = gold_dir() / "files" / "sections" / f"{s['id']}.pdf"
        text = gold.read_text()
        check = {"gold_words_in_layer": gold_in_layer(text, cut),
                 **element_gold.gold_in_clips(text, pdf.page_lines(cut), _clips(s, cut), pdf.page_sizes(cut))}
        gold_checks[s["id"]] = check
        if check["gold_words_in_layer"] < GOLD_IN_LAYER or check["gold_clip_f1"] < GOLD_IN_CLIPS:
            mismatch.append({"id": s["id"], **check})
    skipped = set(no_gold) | {m["id"] for m in mismatch}
    wanted = [s for s in chosen if s["id"] not in skipped]
    rows, failed, builds = [], [], {}
    for engine in engines:
        if engine == ASSEMBLED:
            builds[engine] = {e: builds.get(e) or reading.build(e) for e in ENGINES}
        else:
            builds[engine] = reading.build(engine)
        for entry in wanted:
            if job_id is not None and job_queue.is_cancelled(job_id):
                break
            try:
                rows.append(_member(engine, entry, builds[engine], passes_on) | gold_checks[entry["id"]])
            except Exception as e:
                failed.append({"id": entry["id"], "engine": engine, "error": f"{type(e).__name__}: {e}"[:300]})
        # kept after each engine, so a crash in the next one leaves this one's rows
        if job_id is not None:
            artifacts.atomic_write(settings.DATA_DIR / "eval" / "elements" / f"job-{job_id}.json",
                                   {"code": code_version.LOADED, "builds": builds, "no_gold": no_gold,
                                    "gold_mismatch": mismatch, "rows": rows, "failed": failed})
    by = {engine: _views([r for r in rows if r["engine"] == engine]) for engine in engines}
    if all(e in engines for e in ENGINES):
        by["best_of_both"] = _views(_best_of([r for r in rows if r["engine"] in ENGINES]))
    return {"code": code_version.LOADED, "builds": builds, "knobs": knobs or {}, "sections": len(wanted),
            "no_gold": no_gold, "gold_mismatch": mismatch, "failed": failed, "totals": by}


def _views(rows: list[dict]) -> dict:
    return {"all": _totals(rows), **{lang: _totals([r for r in rows if r["lang"] == lang]) for lang in ("en", "ru")},
            "by_doc": {doc: _totals([r for r in rows if r["doc"] == doc]) for doc in sorted({r["doc"] for r in rows})}}


# each element of a section taken from the engine that read it best: the ceiling of choosing an engine per place
BEST = {"code_exact": max, "code_contained": max, "cells_found": max, "table_rows_exact": max, "headings_found": max,
        "similarity": max,
        "body_f1": max, "code_out_foreign": min, "code_out_merged": min, "headings_phantom": min, "running_leaked": min}


def _best_of(rows: list[dict]) -> list[dict]:
    by_id: dict[str, list[dict]] = {}
    for r in rows:
        by_id.setdefault(r["id"], []).append(r)
    out = []
    for same in by_id.values():
        if len(same) < 2:
            continue
        best = dict(same[0], engine="best_of_both")
        for key, pick in BEST.items():
            best[key] = pick(r[key] for r in same)
        out.append(best)
    return out
