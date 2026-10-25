# the structure stage measured on its own: with bookmarks or all contents switched off against them, or against HiPS
import artifacts
import book_knobs
import code_version
import job_queue
import job_specs
import settings
from engines import card
from job_signals import Final
from orm.catalogue import Book, StructureNode
from orm.db import Session
from sqlalchemy import select
from stages import assemble, intake, run_pieces
from stages.structure import collect, evidence, scan
from stages.structure.sources import Entry
from structure import tree

from evaluation import hips, structure_gold

SETS = job_specs.STRUCTURE_SETS
# the sources a book without contents lacks; the structure they gave is the gold its other sources are scored against
CONTENTS = ("bookmarks", "printed_contents")
# headings read from every page as a picture would put the whole shelf on the GPU lane
CONTENTS_OFF = (*CONTENTS, "headings")


# the bookmarks as the stage reads them: a book whose bookmarks the owner marked as not its contents has no gold
def _gold(book_id: int) -> list:
    marks = collect.book_bookmarks(intake.files_of(book_id), book_knobs.of(book_id)).entries
    return [e for e in marks if e.page is not None]


# the book's current structure when its bookmarks or printed contents gave it
def _structure_gold(book_id: int) -> list:
    version = collect.current_version(book_id)
    if version is None:
        return []
    with Session() as session:
        if evidence.base(session, version.id) not in CONTENTS:
            return []
        query = (select(StructureNode).where(StructureNode.structure_version_id == version.id)
                 .order_by(StructureNode.ord))
        # a node with no page is placed nowhere, so it can be neither found nor missed
        return [Entry(e.title, e.level, e.first_page) for e in session.scalars(query)
                if e.kind != "front_matter" and e.first_page is not None]


def _member(book_id: int, set_name: str = "bookmarks_off") -> dict:
    with Session() as session:
        if scan.is_scan(session.get(Book, book_id)):
            return {"book_id": book_id, "skipped": "a scan: its contents are recognised on the GPU lane"}
    contents_off = set_name == "contents_off"
    gold = _structure_gold(book_id) if contents_off else _gold(book_id)
    if len(gold) < 2:
        return {"book_id": book_id, "skipped": "no structure from contents to score against" if contents_off
                else "no bookmarks to score against"}
    try:
        source, got, found = collect.choose(book_id, off=CONTENTS_OFF if contents_off else ("bookmarks",))
        contents_pages = found["printed_contents"]["notes"].get("pages") or []
    except card.WrongLane as e:
        return {"book_id": book_id, "skipped": f"needs the GPU lane: {e}"}
    except Final as e:
        got, source, contents_pages, found = [], f"none: {e}", [], {}
    # a book with no contents of its own is a case for other ways (the web, computed headings), not a miss
    printed = "contents" if contents_pages else "no printed contents"
    service = _service(got, source, found.get("pages", 0), frozenset(contents_pages), intake.files_of(book_id),
                       book_knobs.of(book_id)["structure.reading_level"])
    return {"book_id": book_id, "source": source, "printed": printed,
            **structure_gold.score(gold, got, max(contents_pages) if contents_pages else None, service)}


# the nodes the run's role rule makes service, from the pieces a new run of the book would read
def _service(got: list[Entry], source: str, pages: int, contents: frozenset[int], files,
             owners_level: int | None = None) -> list[Entry]:
    if not got:
        return []
    entries = collect.with_front_matter(got, files)
    rows = collect.with_parents(collect.structure_rows(got, source, pages, files))
    cut = frozenset().union(*assemble.cut_of(rows, contents).values())
    pieces = assemble.pieces_of(rows, cut, run_pieces.level_for(owners_level,
                                                                  tree.reading_level([r["level"] for r in rows])))
    return [entries[p["ord"] - 1] for p in pieces if p["role"] == "service"]


# a HiPS book enters the catalogue like any other and its structure stage runs as usual, then meets the gold
def _hips_member(name: str, job_id: int | None) -> dict:
    book_id, _ = intake.register([(hips.pdf_path(name), f"{name}.pdf")])
    intake.probe(book_id)

    # the same lane choice as the structure stage, so the scored structure is the one the stage builds
    def to_gpu(because: str) -> dict:
        handed = job_queue.enqueue("structure_scan", {"book_id": book_id, "what": ["structure"]}, book_id=book_id)
        return {"book_id": book_id, "name": name,
                "skipped": f"its structure waits on the GPU lane in job {handed}: {because}"}

    if collect.wants_raster(book_id):
        return to_gpu("the contents are read from the raster")
    try:
        collect.collect(book_id, job_id)
    except card.WrongLane as e:
        return to_gpu(str(e))
    except Final as e:
        return {"book_id": book_id, "name": name, "source": f"none: {e}", **structure_gold.score(hips.gold(name), [])}
    version = collect.current_version(book_id)
    with Session() as session:
        query = (select(StructureNode).where(StructureNode.structure_version_id == version.id)
                 .order_by(StructureNode.ord))
        rows = session.scalars(query).all()
        front_end = next((e.last_page for e in rows if e.kind == "front_matter"), None)
        got = [Entry(e.title, e.level, e.first_page) for e in rows if e.kind != "front_matter"]
    # gold entries inside our front matter keep their pages in the book, so they are listed apart, not missed
    return {"book_id": book_id, "name": name, "source": "structure",
            **structure_gold.score(hips.gold(name), got, front_end)}


# a cancel is read between books, so a long set stops at the next one
def run(set_name: str, book_ids: list[int] | None, job_id: int | None) -> dict:
    if set_name not in SETS:
        raise Final(f"set {set_name!r} is not built yet; built: {SETS}")
    rows = []
    if set_name == "hips":
        for name in hips.fetch():
            if job_id is not None and job_queue.is_cancelled(job_id):
                break
            row = _hips_member(name, job_id)
            rows.append(row)
            _keep(row["book_id"], set_name, row)
        return _summary(set_name, rows, [r for r in rows if "skipped" not in r])
    with Session() as session:
        books = select(Book.id) if set_name == "contents_off" else select(Book.id).where(Book.has_bookmarks)
        ids = book_ids or list(session.scalars(books.order_by(Book.id)))
    for book_id in ids:
        if job_id is not None and job_queue.is_cancelled(job_id):
            break
        row = _member(book_id, set_name)
        rows.append(row)
        _keep(book_id, set_name, row)
    # with all contents off a book's own contents pages are no reason to leave it out
    scored = [r for r in rows if "skipped" not in r and (set_name == "contents_off" or r["printed"] == "contents")]
    return _summary(set_name, rows, scored)


# a score changes with the structure code and with the scoring code, so both stamp the artifact
def _keep(book_id: int, name: str, row: dict) -> None:
    # service pieces are split off by the assembly's role rule, so its code scores as well
    scoring = code_version.files_hash([*sorted((settings.APP_DIR / "evaluation").glob("*.py")),
                                       settings.APP_DIR / "stages" / "assemble.py"]).hexdigest()[:16]
    made_from = artifacts.Inputs({"stage": "structure_eval", "set": name, "code": collect.code_hash(),
                                  "scoring": scoring, "files": [f.sha256 for f in intake.files_of(book_id)]})
    artifacts.write(artifacts.Owner(book_id=book_id), artifacts.book_dir(book_id), "structure_eval", f"{name}.json",
                    row, made_from)


def _summary(name: str, rows: list[dict], scored: list[dict]) -> dict:
    top_total = sum(r["top_nodes"] for r in scored)
    found = sum(r["top_nodes_found"] for r in scored)
    return {
        "set": name, "books": len(scored), "skipped": [r for r in rows if "skipped" in r],
        "no_printed_contents": [{"book_id": r["book_id"], "source": r["source"], "top_nodes": r["top_nodes"],
                                 "top_nodes_found": r["top_nodes_found"]}
                                for r in rows if "skipped" not in r and r.get("printed", "contents") != "contents"],
        "top_nodes": top_total, "top_nodes_found": found,
        "top_nodes_found_share": round(found / top_total, 3) if top_total else None,
        "top_nodes_below_top": sum(r["top_nodes_below_top"] for r in scored),
        "extra_top_nodes": sum(r["extra_top_nodes"] for r in scored),
        "books_with_missed_top_nodes": [{"book_id": r["book_id"], "source": r["source"],
                                        "missed": r["missed_top_nodes"]} for r in scored if r["missed_top_nodes"]],
        "rows": [{k: v for k, v in r.items() if k not in ("missed_top_nodes", "extra_top_node_titles")}
                 for r in scored],
    }
