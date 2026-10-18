# what a job type costs from its latest done jobs, and how long the work in flight has left at those prices
import worker_registry
from orm.db import Session
from orm.jobs import Job
from sqlalchemy import func, select

COST_SAMPLE = 200


# a read that took every range from the kept readings costs a lookup; it is priced apart from one that read
KEPT = ".kept"
# a read from before reads said so is taken as kept when it took less than this many seconds
CACHED_READ = 1.0


def kept_read(elapsed: float | None, kept: bool | None) -> bool:
    return kept if kept is not None else (elapsed or 0) < CACHED_READ


def _priced_as(type: str, kept: bool | None) -> str:
    return type + KEPT if kept else type


# what a type costs: elapsed seconds of its latest done jobs, so a batch can be priced before and while it runs
def costs() -> dict[str, dict]:
    kept = Job.result["kept"].as_boolean()
    with Session() as session:
        ranked = select(Job.type, Job.elapsed, kept.label("kept"), func.row_number().over(
            partition_by=(Job.type, kept), order_by=Job.id.desc()).label("n")).where(
            Job.status == "done", Job.elapsed.is_not(None)).subquery()
        rows = session.execute(select(ranked.c.type, ranked.c.elapsed, ranked.c.kept)
                               .where(ranked.c.n <= COST_SAMPLE)).all()
    seen: dict[str, list[float]] = {}
    told = {type for type, _, was_kept in rows if was_kept is not None}
    # jobs from before a type told kept reads apart mix both and are left out once it does
    for type, elapsed, was_kept in rows:
        if was_kept is not None or type not in told:
            seen.setdefault(_priced_as(type, was_kept), []).append(elapsed)
    out = {}
    for type, values in seen.items():
        values.sort()
        out[type] = {"jobs": len(values), "median": round(values[len(values) // 2], 2),
                     "p90": round(values[int(len(values) * 0.9)], 2)}
    return out


# queued and running work at each type's median, one gpu thread, cpu threads shared; a queued read priced as a real one
def seconds_left(active: list[Job], running: list[dict]) -> dict[str, float | None]:
    priced, spent = costs(), {r["id"]: r["seconds"] for r in running}
    threads = worker_registry.lane_threads()
    out: dict[str, float | None] = {}
    for lane, n in threads.items():
        jobs = [j for j in active if j.lane == lane]
        if not jobs:
            continue
        if any(j.type not in priced for j in jobs):
            out[lane] = None
            continue
        left = sum(max(priced[j.type]["median"] - spent.get(j.id, 0.0), 0.0) for j in jobs)
        out[lane] = round(left / n)
    return out
