import job_queue
import job_specs
from knobs import registry
from mcp_tools import tool
from orm.catalogue import Book
from orm.db import Session
from sqlalchemy import select

BUILT_TOC_SETS = ("bookmarks_off", "hips")


# the door's argument is named set, as its contract has it, so the builtin is kept under another name
set_of = set


# scores land in the job's result and in each book's artifacts; the gold sets come with their fetch job
@tool("toc_eval", "POST /v1/eval/toc",
      "Queues a toc evaluation job (cpu lane) over a gold set (bookmarks_off or hips), optionally on some "
      "books; scores land in the job's result and each book's artifacts. Returns {job_id}.")
def toc_eval(set: str, book_ids: list[int] | None = None) -> dict:
    options = job_specs.check("toc_eval", {"set": set, "book_ids": book_ids})
    if set not in BUILT_TOC_SETS:
        raise job_specs.Refused(f"set {set!r} is not built yet; built: {BUILT_TOC_SETS}")
    if book_ids:
        with Session() as session:
            known = set_of(session.scalars(select(Book.id).where(Book.id.in_(book_ids))))
        if missing := sorted(set_of(book_ids) - known):
            raise LookupError(f"no books {missing}")
    return {"job_id": job_queue.enqueue("toc_eval", options)}


TOC_TOTALS = ("books", "chapters", "chapters_found", "chapters_found_share", "chapters_below_top", "extra_chapters")
TOC_ROW = ("source", "chapters", "chapters_found", "chapters_below_top", "extra_chapters", "entries_matched",
           "recall", "precision", "level_agreement")


def _toc_result(job_id: int) -> dict:
    job = job_queue.get(job_id)
    if job is None or job.type != "toc_eval":
        raise LookupError(f"no toc_eval job {job_id}")
    if job.status != "done":
        raise job_specs.Refused(f"toc_eval job {job_id} is {job.status}, not done")
    return job.result or {}


# one row per book whatever became of it: scored, scored without printed contents, or skipped with the reason
def _toc_rows(result: dict) -> dict[int, dict]:
    missed = {r["book_id"]: sorted(m["title"] for m in r["missed"])
              for r in result.get("books_with_missed_chapters", [])}
    out = {r["book_id"]: {"status": "skipped", "skipped": r["skipped"]} for r in result.get("skipped", [])}
    for r in result.get("no_printed_contents", []):
        out[r["book_id"]] = {"status": "no_printed_contents", **{k: r.get(k) for k in TOC_ROW if k in r}}
    for r in result.get("rows", []):
        out[r["book_id"]] = {"status": "scored", **{k: r.get(k) for k in TOC_ROW},
                             "missed": missed.get(r["book_id"], [])}
    return out


# two toc evaluations of one set side by side: the totals with their deltas and every book whose row moved
@tool("toc_eval_compare", "GET /v1/eval/toc/compare",
      "Two toc evaluations of one set side by side: the totals with deltas and every book whose row moved; refuses"
      " jobs of different sets or not done.")
def toc_eval_compare(job_a: int, job_b: int) -> dict:
    a, b = _toc_result(job_a), _toc_result(job_b)
    if a.get("set") != b.get("set"):
        raise job_specs.Refused(f"job {job_a} scored set {a.get('set')!r} and job {job_b} set {b.get('set')!r}")
    totals = {k: {"a": a.get(k), "b": b.get(k),
                  "delta": round(b[k] - a[k], 3) if isinstance(a.get(k), int | float)
                  and isinstance(b.get(k), int | float) else None} for k in TOC_TOTALS}
    rows_a, rows_b = _toc_rows(a), _toc_rows(b)
    moved = []
    for book_id in sorted(rows_a.keys() | rows_b.keys()):
        before, after = rows_a.get(book_id), rows_b.get(book_id)
        if before != after:
            changed = sorted(k for k in (before or {}).keys() | (after or {}).keys()
                             if (before or {}).get(k) != (after or {}).get(k))
            moved.append({"book_id": book_id, "changed": changed, "a": before, "b": after})
    return {"set": a.get("set"), "job_a": job_a, "job_b": job_b, "totals": totals, "moved": moved,
            "unchanged": len(rows_a.keys() | rows_b.keys()) - len(moved)}


# rows land in data/eval/elements/job-<id>.json, totals per engine and language in the job's result
@tool("element_eval", "POST /v1/eval/elements",
      "Queues an element evaluation job (gpu lane) that reads rag-lab's converter_gold sections with each "
      "engine and scores code, tables, headings and text; `knobs` shape the assembled reading. Returns "
      "{job_id}.")
def element_eval(engines: list[str] | None = None, ids: list[str] | None = None, knobs: dict | None = None) -> dict:
    registry.check(knobs or {})
    options = job_specs.check("element_eval", {k: v for k, v in {"engines": engines, "ids": ids, "knobs": knobs}.items()
                                               if v})
    return {"job_id": job_queue.enqueue("element_eval", options)}
