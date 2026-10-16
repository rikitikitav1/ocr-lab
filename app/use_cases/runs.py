# a book run through the doors: start one on the current metadata and structure, read it and its pieces
import io
import json
import tarfile
from pathlib import Path

import artifacts
import book_knobs
import job_queue
import job_specs
import profiles
import settings
from job_signals import Final
from mcp_tools import tool
from orm.catalogue import (
    Artifact,
    Book,
    MetadataVersion,
    Piece,
    Profile,
    Run,
    RunStatus,
    StructureNode,
    StructureVersion,
)
from orm.db import Session
from orm.jobs import Job
from sqlalchemy import func, select
from stages import eta, result_run, run_state, versions
from stages import run_pieces as units_of_run


def _view(run: Run) -> dict:
    return {"id": run.id, "book_id": run.book_id, "status": run.status, "stage": run.stage, "format": run.format,
            "metadata_version_id": run.metadata_version_id, "structure_version_id": run.structure_version_id,
            "profile_id": run.profile_id, "bundle_dir": run.bundle_dir, "created_at": run.created_at}


def _startable(session, id: int, format: str, profile_id: int | None) -> tuple[StructureVersion, int]:
    if format != "markdown":
        raise job_specs.Refused(f"format {format!r} is not built; built: markdown")
    if session.get(Book, id) is None:
        raise LookupError(f"no book {id}")
    structure = versions.current(session, StructureVersion, id)
    if structure is None:
        raise job_specs.Refused(f"book {id} has no structure yet; recollect structure first")
    if profile_id is None:
        return structure, profiles.resolve(session, id).id
    if (given := session.get(Profile, profile_id)) is None or given.book_id != id:
        raise job_specs.Refused(f"profile {profile_id} is not a profile of book {id}")
    return structure, profile_id


def _start(session, id: int, format: str, structure: StructureVersion, profile_id: int) -> tuple[Run, int]:
    meta = versions.current(session, MetadataVersion, id)
    run = Run(book_id=id, profile_id=profile_id, structure_version_id=structure.id, format=format,
              metadata_version_id=meta.id if meta is not None else None, dir="", status="queued",
              reading_level=units_of_run.level_for(book_knobs.of(id)["structure.reading_level"],
                                                  units_of_run.rows(session, structure.id)))
    session.add(run)
    session.flush()
    run.dir = str(artifacts.run_dir(id, run.id))
    return run, job_queue.enqueue("book_run", {"run_id": run.id}, run_id=run.id, book_id=id, session=session)


# until profile search exists a run asking for it runs on the default preset and says so
@tool("start_run", "POST /v1/books/{id}/runs",
      "Starts a book run on the current structure and metadata with the given or resolved profile and queues its "
      "book_run job (cpu lane; pieces then read on the gpu lane). Returns the run and job_id; follow the job "
      "with wait_job.")
def start_run(id: int, format: str = "markdown", profile_id: int | None = None, search: bool = True) -> dict:
    with Session() as session:
        structure, profile_id = _startable(session, id, format, profile_id)
        run, job = _start(session, id, format, structure, profile_id)
        session.commit()
        view = _view(run)
    return {"run": view, "job_id": job, "search": profiles.SEARCH_SKIPPED if search else None,
            "eta": eta.estimate(id, view["id"])}


# every book is checked before any run is queued, so a refusal leaves nothing half started
@tool("start_runs", "POST /v1/runs",
      "Start a run for each of several books on their current structure and metadata; every book is checked first, "
      "so none"
      " starts if one is refused. Returns the runs and job ids.")
def start_runs(book_ids: list[int], format: str = "markdown") -> dict:
    if not book_ids:
        raise job_specs.Refused("no books given")
    with Session() as session:
        checked, refused = {}, []
        for id in dict.fromkeys(book_ids):
            try:
                checked[id] = _startable(session, id, format, None)
            except (LookupError, job_specs.Refused) as e:
                refused.append(f"book {id}: {e}")
        if refused:
            raise job_specs.Refused("no run started; " + "; ".join(refused))
        started = [_start(session, id, format, found, profile_id) for id, (found, profile_id) in checked.items()]
        session.commit()
        return {"runs": [{"run_id": run.id, "book_id": run.book_id, "job_id": job} for run, job in started]}


# a run stopped by its own start or bundle, not by a piece, names the job and the error that stopped it
def _run_errors(session, run: Run) -> list[dict]:
    if run.status != RunStatus.ATTENTION:
        return []
    out = []
    for type in ("book_run", "book_metrics"):
        last = session.scalar(select(Job).where(Job.run_id == run.id, Job.type == type).order_by(Job.id.desc()))
        if last is not None and last.status == "error":
            out.append({"job": last.id, "type": type, "error": (last.error or {}).get("error")})
    return out


# why each run waits in attention: its start or bundle job's error, and its failed pieces with theirs
def stopped(session, run_ids: set[int]) -> list[dict]:
    runs = session.scalars(select(Run).where(Run.id.in_(run_ids), Run.status == RunStatus.ATTENTION)
                           .order_by(Run.id))
    return [{"run_id": run.id, "errors": _run_errors(session, run),
             "failed_pieces": [{"ord": c.ord, "errors": c.errors} for c in session.scalars(
                 select(Piece).where(Piece.run_id == run.id, Piece.status == "failed").order_by(Piece.ord))]}
            for run in runs]


def _piece_counts(session, run_ids: list[int]) -> dict[int, dict]:
    counts: dict[int, dict] = {id: {} for id in run_ids}
    for run_id, status, n in session.execute(select(Piece.run_id, Piece.status, func.count())
                                             .where(Piece.run_id.in_(run_ids))
                                             .group_by(Piece.run_id, Piece.status)):
        counts[run_id][status] = n
    return counts


# engine-major reading leaves every piece pending until the last engine reaches it, so reads are counted per engine
def _reads(session, id: int) -> dict:
    latest: dict[tuple, tuple[int, str]] = {}
    for options, status in session.execute(select(Job.options, Job.status).where(Job.run_id == id,
                                                                                  Job.type == "read_piece")):
        place, round = (options["ord"], options["engine"]), int(options.get("round", 0))
        if place not in latest or round >= latest[place][0]:
            latest[place] = (round, status)
    out: dict = {}
    for (_, engine), (_, status) in sorted(latest.items()):
        tally = out.setdefault(engine, {"total": 0})
        tally["total"] += 1
        tally[status] = tally.get(status, 0) + 1
    return out


@tool("run", "GET /v1/runs/{id}",
      "One run: status, stage, profile, versions it used, piece counts by status, reads per engine of the"
      " latest round, the code it runs on, and the errors of its start or bundle jobs; reading changes nothing.")
def get_run(id: int) -> dict:
    with Session() as session:
        run = session.get(Run, id)
        if run is None:
            raise LookupError(f"no run {id}")
        return {**_view(run), "code_hash": run.code_hash, "pieces": _piece_counts(session, [id])[id],
                "reads": _reads(session, id), "errors": _run_errors(session, run)}


def _report_of(session, id: int) -> dict | None:
    row = session.scalar(select(Artifact).where(Artifact.run_id == id, Artifact.name == "report.json",
                                                Artifact.removed_at.is_(None)).order_by(Artifact.id.desc()))
    return json.loads(artifacts.read(row)) if row is not None else None


def _brief(run: Run, pieces: dict) -> dict:
    return {"id": run.id, "book_id": run.book_id, "status": run.status, "stage": run.stage,
            "code_hash": run.code_hash, "created_at": run.created_at, "pieces": pieces}


# the shelf at a glance: brief rows, and for a finished run its pages and seconds per page from the report
@tool("runs", "GET /v1/runs",
      "List runs, filtered by ids, book or status: brief rows with status, pages and, for done runs, seconds per page.")
def list_runs(ids: list[int] | None = None, book_id: int | None = None, status: str | None = None,
              limit: int = 50) -> list[dict]:
    query = select(Run).order_by(Run.id.desc()).limit(limit)
    query = query.where(Run.id.in_(ids)) if ids else query
    query = query.where(Run.book_id == book_id) if book_id is not None else query
    query = query.where(Run.status == status) if status is not None else query
    with Session() as session:
        found = list(session.scalars(query))
        counts = _piece_counts(session, [r.id for r in found])
        rows = []
        for run in found:
            row = _brief(run, counts[run.id])
            if run.status == RunStatus.DONE and (report := _report_of(session, run.id)) is not None:
                seconds = report.get("seconds") or {}
                row |= {"pages": seconds.get("pages"), "seconds_per_page": seconds.get("per_page")}
            rows.append(row)
        return rows


# a run read by chapters has no tree pieces to name the nodes of; its pieces are its chapters
def _held(session, run: Run) -> dict[int, list[int]]:
    try:
        return {u["ord"]: [n["ord"] for n in u["nodes"]] for u in units_of_run.pieces(session, run)}
    except Final:
        return {}


@tool("nodes", "GET /v1/runs/{id}/nodes",
      "A run's pieces in order, each with the nodes it holds (a piece is a node of the reading level with the "
      "nodes under it), status, engine, checks, errors and seconds.")
def run_pieces(id: int) -> list[dict]:
    with Session() as session:
        run = session.get(Run, id)
        if run is None:
            raise LookupError(f"no run {id}")
        held = _held(session, run)
        return [{"ord": c.ord, "node_id": c.node_id, "nodes": held.get(c.ord, [c.ord]), "status": c.status,
                 "engine": c.engine, "checks": c.checks, "errors": c.errors, "seconds": c.seconds}
                for c in session.scalars(select(Piece).where(Piece.run_id == id).order_by(Piece.ord))]


def _run(session, id: int) -> Run:
    run = session.get(Run, id)
    if run is None:
        raise LookupError(f"no run {id}")
    return run


# the newest report the run's book metrics wrote; a run still assembling has none yet
@tool("report", "GET /v1/runs/{id}/report",
      "The newest report.json of a run (per phase and per page seconds, structure base, worst pieces); missing "
      "until book metrics have run.")
def run_report(id: int) -> dict:
    with Session() as session:
        _run(session, id)
        report = _report_of(session, id)
    if report is None:
        raise LookupError(f"run {id} has no report yet: book metrics have not run")
    return report


def _artifact_view(a: Artifact) -> dict:
    return {"id": a.id, "stage": a.stage, "piece": a.piece_ord, "name": a.name, "path": a.path,
            "sha256": a.sha256, "heavy": a.heavy, "created_at": a.created_at}


@tool("run_artifacts", "GET /v1/runs/{id}/artifacts",
      "Lists a run's artifacts (id, stage, piece, name, path, size flags), optionally by stage or by `node` "
      "ord (the artifacts of the piece holding that node); read one with run_artifact.")
def run_artifacts(id: int, stage: str | None = None, node: int | None = None) -> list[dict]:
    with Session() as session:
        run = _run(session, id)
        piece = next((p for p, nodes in _held(session, run).items() if node in nodes), node)
        query = select(Artifact).where(Artifact.run_id == id, Artifact.removed_at.is_(None))
        query = query.where(Artifact.stage == stage) if stage is not None else query
        query = query.where(Artifact.piece_ord == piece) if node is not None else query
        return [_artifact_view(a) for a in session.scalars(query.order_by(Artifact.id))]


def _artifact_row(id: int, artifact_id: int) -> Artifact:
    with Session() as session:
        _run(session, id)
        row = session.get(Artifact, artifact_id)
        if row is None or row.run_id != id or row.removed_at is not None:
            raise LookupError(f"run {id} has no artifact {artifact_id}")
        return row


# a tool cannot carry bytes, so it gets the file as text; the route sends it raw
@tool("run_artifact", "GET /v1/runs/{id}/artifacts/{artifact_id}",
      "One run artifact with its file content as text.")
def run_artifact(id: int, artifact_id: int) -> dict:
    row = _artifact_row(id, artifact_id)
    return {**_artifact_view(row), "text": artifacts.read(row).decode(errors="replace")}


def artifact_file(id: int, artifact_id: int) -> tuple[str, bytes]:
    row = _artifact_row(id, artifact_id)
    return row.name, artifacts.read(row)


def _bundle_dir(id: int) -> tuple[Run, Path]:
    with Session() as session:
        run = _run(session, id)
        if not run.bundle_dir:
            raise LookupError(f"run {id} has no bundle yet: it is {run.status}")
        return run, settings.DATA_DIR / run.bundle_dir


def _bundle_files(base) -> list[str]:
    return sorted(str(p.relative_to(base)) for p in base.rglob("*") if p.is_file())


# a tool cannot carry the archive, so it gets the bundle's place and files; the route sends the tar
@tool("bundle", "GET /v1/runs/{id}/bundle",
      "A run's bundle: the report's numbers, a download link to the bundle as one tar, the directory and its files.")
def run_bundle(id: int) -> dict:
    run, base = _bundle_dir(id)
    report = base / "report.json"
    numbers = json.loads(report.read_text()).get("numbers") if report.exists() else None
    return {"run": id, "book": run.book_id, "numbers": numbers,
            "download": f"{settings.STAND_URL}/v1/runs/{id}/bundle", "bundle_dir": run.bundle_dir,
            "files": _bundle_files(base)}


def _result_of(book_id: int) -> int:
    with Session() as session:
        book = session.get(Book, book_id)
        if book is None:
            raise LookupError(f"no book {book_id}")
        best = book.result_run_id
    # an empty pointer (old runs, or a structure collected again) is filled now by the same rule a finished run uses
    if best is None:
        best = result_run.recompute(book_id)
    if best is None:
        raise LookupError(f"book {book_id} has no finished run on its current structure")
    return best


@tool("book_bundle", "GET /v1/books/{id}/bundle",
      "The bundle of a book's result run (the best finished run on its current structure), as `bundle`: numbers and a"
      " download link.")
def book_bundle(id: int) -> dict:
    return run_bundle(_result_of(id))


# the bundle as one tar, its files at the top so moving the directory keeps every image link
def bundle_tar(id: int) -> tuple[str, bytes]:
    run, base = _bundle_dir(id)
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w") as tar:
        for name in _bundle_files(base):
            tar.add(base / name, arcname=name)
    return f"book-{run.book_id}-run-{id}.tar", out.getvalue()


def book_bundle_tar(id: int) -> tuple[str, bytes]:
    return bundle_tar(_result_of(id))


def _refused_while_running(action):
    try:
        return action()
    except ValueError as e:
        raise job_specs.Refused(str(e)) from e


# overrides go into a profile derived for this piece; the rerun makes it the run's profile under its lock
def _derived(id: int, ord: int, overrides: dict) -> int:
    with Session() as session:
        run = session.get(Run, id)
        if run is None:
            raise LookupError(f"no run {id}")
        if run_state.busy(run):
            raise job_specs.Refused(f"run {id} is still running")
        base = run.profile_id if run.profile_id is not None else profiles.resolve(session, run.book_id).id
        session.commit()
    return profiles.derive(base, pieces={ord: overrides})["id"]


# one piece assembled again from its kept readings, then the book's numbers and bundle
@tool("rerun_node", "POST /v1/runs/{id}/nodes/{ord}/rerun",
      "Assembles the unit holding a node again from its kept readings, with `overrides` as knob values in a "
      "profile derived for that unit, then redoes the book metrics and bundle; queues jobs and returns the run "
      "with the unit's ord and every node it holds, since they all move together. Refused while the run is "
      "still running.")
def rerun_node(id: int, ord: int, overrides: dict | None = None) -> dict:
    unit, nodes = _unit_of(id, ord)
    profile_id = _derived(id, unit, overrides) if overrides else None
    _refused_while_running(lambda: run_state.rerun_piece(id, unit, profile_id))
    return {**get_run(id), "unit": unit, "nodes_rerun": nodes}


# a node is read and assembled with the unit that holds it, so its rerun is that unit's
def _unit_of(id: int, ord: int) -> tuple[int, list[int]]:
    with Session() as session:
        run = session.get(Run, id)
        if run is None:
            raise LookupError(f"no run {id}")
        units = units_of_run.pieces(session, run)
        row = next((r for r in units_of_run.rows(session, run.structure_version_id) if r["ord"] == ord), None)
    unit = units_of_run.holding(units, ord, row and row["first_page"])
    if unit is None:
        raise LookupError(f"run {id} has no node {ord} in a unit")
    return unit["ord"], [n["ord"] for n in unit["nodes"]]


@tool("resume_run", "POST /v1/runs/{id}/resume",
      "Restarts the pieces of a stopped run that are not done (the done ones keep their artifacts); queues "
      "jobs and returns the run with pieces_restarted. Refused while it is running.")
def resume_run(id: int) -> dict:
    pieces = _refused_while_running(lambda: run_state.resume(id))
    return {**get_run(id), "pieces_restarted": pieces}


@tool("cancel_run", "POST /v1/runs/{id}/cancel",
      "Cancels a run's live jobs and returns the run with jobs_cancelled.")
def cancel_run(id: int) -> dict:
    jobs = run_state.cancel(id)
    return {**get_run(id), "jobs_cancelled": jobs}


RUN_ENDS = (RunStatus.DONE, RunStatus.CANCELLED)


def _known_runs(session, ids: list[int]) -> dict[int, Run]:
    if not ids:
        raise job_specs.Refused("no runs given")
    found = {r.id: r for r in session.scalars(select(Run).where(Run.id.in_(ids)))}
    if missing := sorted(set(ids) - set(found)):
        raise LookupError(f"no runs {missing}")
    return found


# a run waiting in attention has settled; a done or cancelled one once its last job has ended too
def _settled_runs(ids: list[int], until: str) -> dict | None:
    with Session() as session:
        found = _known_runs(session, ids)
        live = set(session.scalars(select(Job.run_id).where(Job.run_id.in_(ids), Job.status.in_(job_queue.ACTIVE))))
        settled = [i for i, r in found.items()
                   if r.status == RunStatus.ATTENTION or (r.status in RUN_ENDS and i not in live)]
    if len(settled) == len(found) or (until == "any" and settled):
        return {"settled": sorted(settled)}
    return None


# blocks until every run, or any with until="any", is done, cancelled or needs attention, and says why each stopped
@tool("wait_runs", "GET /v1/runs/wait",
      "Wait until all (or any) of the given runs are done, cancelled or in attention, up to the timeout; returns each"
      " run's status.")
def wait_runs(ids: list[int], timeout: float = 600, until: str = "all") -> dict:
    if until not in ("all", "any"):
        raise job_specs.Refused(f"until is all or any, not {until!r}")
    ids = sorted(set(ids))
    _settled_runs(ids, until)
    got = job_queue.listen(lambda: _settled_runs(ids, until), timeout)
    with Session() as session:
        found = _known_runs(session, ids)
        counts = _piece_counts(session, ids)
        return {"settled": got is not None, "timeout": got is None,
                "runs": [_brief(found[i], counts[i]) for i in ids], "stopped_runs": stopped(session, set(ids))}


# every run is checked first; finished runs are left as they are, and dry_run names the jobs a cancel would stop
@tool("cancel_runs", "POST /v1/runs/cancel",
      "Cancel several runs and their jobs; dry_run lists what would be cancelled; runs already done or cancelled are"
      " skipped.")
def cancel_runs(ids: list[int], dry_run: bool = False) -> dict:
    with Session() as session:
        found = _known_runs(session, sorted(set(ids)))
    skipped = sorted(i for i, r in found.items() if r.status in RUN_ENDS)
    todo = sorted(set(found) - set(skipped))
    stop = (lambda i: job_queue.live_ids(run_id=i)) if dry_run else run_state.cancel
    return {"dry_run": dry_run, "runs": [{"run_id": i, "jobs": stop(i)} for i in todo], "skipped": skipped}


COMPARED = ("lost_words", "extra_words", "subs", "subs_found", "lost_text", "extra_text")


# a run's pieces by place: by ord on one structure version, by structure title and first page across two
def _places(session, run: Run, by_ord: bool) -> dict:
    rows = session.execute(select(Piece, StructureNode.title, StructureNode.first_page)
                           .outerjoin(StructureNode, StructureNode.id == Piece.node_id)
                           .where(Piece.run_id == run.id).order_by(Piece.ord))
    return {(c.ord if by_ord else (title, first)): (c, title) for c, title, first in rows}


def _numbers(report: dict | None) -> dict:
    numbers = (report or {}).get("numbers") or {}
    return {k: v for k, v in numbers.items() if isinstance(v, int | float) and not isinstance(v, bool)}


def _total(side: dict, key: str) -> float:
    values = [(c.checks or {}).get(key) for c, _ in side.values() if c.status == "done"]
    return round(sum(v for v in values if isinstance(v, int | float)), 3)


# two runs of one book side by side: the report numbers, sums of the keys, and only the pieces whose keys moved
@tool("compare_runs", "GET /v1/runs/compare",
      "Two runs of one book side by side: their report numbers with the deltas and the pieces whose numbers moved.")
def compare_runs(a: int, b: int, keys: list[str] | None = None) -> dict:
    keys = keys or list(COMPARED)
    with Session() as session:
        run_a, run_b = _run(session, a), _run(session, b)
        if run_a.book_id != run_b.book_id:
            raise job_specs.Refused(f"run {a} is of book {run_a.book_id} and run {b} of book {run_b.book_id}")
        same_structure = run_a.structure_version_id == run_b.structure_version_id
        side_a, side_b = _places(session, run_a, same_structure), _places(session, run_b, same_structure)
        numbers_a, numbers_b = _numbers(_report_of(session, a)), _numbers(_report_of(session, b))
    moved = []
    for place in [p for p in side_a if p in side_b]:
        (ca, title), (cb, _) = side_a[place], side_b[place]
        diff = {k: [(ca.checks or {}).get(k), (cb.checks or {}).get(k)] for k in keys}
        diff = {k: v for k, v in diff.items() if v[0] != v[1]}
        if ca.status != cb.status:
            diff["status"] = [ca.status, cb.status]
        if diff:
            moved.append({"ord": [ca.ord, cb.ord], "title": title, **diff})
    return {"a": a, "b": b, "same_structure": same_structure,
            "numbers": {k: [numbers_a.get(k), numbers_b.get(k)] for k in sorted(set(numbers_a) | set(numbers_b))},
            "totals": {k: [_total(side_a, k), _total(side_b, k)] for k in keys}, "pieces_moved": moved,
            "only_in_a": [side_a[p][0].ord for p in side_a if p not in side_b],
            "only_in_b": [side_b[p][0].ord for p in side_b if p not in side_a]}
