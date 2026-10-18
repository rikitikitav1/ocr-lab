# the workers the stand knows: their beats and lanes, and the database locks that tell one alive and hold the GPU
import hashlib

import settings
from orm import db
from orm.db import Session
from sqlalchemy import text

# a worker beats this often and is gone after four beats missed: its jobs in hand may then be taken back
HEARTBEAT_SECONDS = 30
STALE_SECONDS = 4 * HEARTBEAT_SECONDS


# a worker silent for a day is gone for good (a container made anew takes a new host name), so its row goes
FORGOTTEN_AFTER = "1 day"


# the worker says which code it runs and that it is alive, idle or not, so the stand never guesses from old jobs
def heartbeat(host: str, code: str, started: bool = False, lanes: tuple[str, ...] = ("cpu", "gpu"),
              cpu_threads: int = settings.CPU_LANE_THREADS) -> None:
    with Session() as session:
        session.execute(text("INSERT INTO workers (host, code, lanes, cpu_threads) VALUES (:host, :code, :lanes, "
                             ":threads) ON CONFLICT (host) DO UPDATE SET code = :code, lanes = :lanes, "
                             "cpu_threads = :threads, seen_at = now()" + (", started_at = now()" if started else "")),
                        {"host": host, "code": code, "lanes": ",".join(lanes), "threads": cpu_threads})
        session.execute(text("DELETE FROM workers WHERE seen_at < now() - CAST(:age AS interval)"),
                        {"age": FORGOTTEN_AFTER})
        session.commit()


# every worker row by host: its code, lanes, when it started and beat, and whether it beat within the window
def workers(session=None) -> dict[str, dict]:
    def read(s) -> dict[str, dict]:
        rows = s.execute(text("SELECT host, code, lanes, cpu_threads, started_at, "
                              "extract(epoch FROM now() - seen_at) AS ago FROM workers"))
        return {r.host: {"code": r.code, "lanes": r.lanes.split(","), "cpu_threads": r.cpu_threads,
                         "started_at": r.started_at,
                         "seconds_ago": round(float(r.ago)), "alive": float(r.ago) < STALE_SECONDS} for r in rows}

    if session is not None:
        return read(session)
    with Session() as s:
        return read(s)


def live_workers(session=None) -> dict[str, dict]:
    return {h: w for h, w in workers(session).items() if w["alive"]}


# the one code every live worker runs, "mixed" while some are behind, None with no worker seen
def worker_code(live: dict[str, dict]) -> str | None:
    codes = {w["code"] for w in live.values()}
    return None if not codes else codes.pop() if len(codes) == 1 else "mixed"


# threads serving each lane across the live workers, each its own count; one worker's when none is seen
def lane_threads() -> dict[str, int]:
    live = live_workers().values()
    cpu = sum(w["cpu_threads"] for w in live if "cpu" in w["lanes"])
    return {"gpu": 1, "cpu": cpu or settings.CPU_LANE_THREADS}


# the GPU lane is held by one worker for its life through a database lock on a connection of its own
GPU_LOCK = 4015


def hold_gpu_lane():
    connection = db.engine.connect().execution_options(isolation_level="AUTOCOMMIT")
    if connection.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": GPU_LOCK}).scalar():
        return connection
    connection.close()
    return None


# a worker holds a lock keyed by its host for its life, so another one tells a dead worker by taking that lock
HOST_LOCK = 4016


def _host_key(host: str) -> int:
    return int(hashlib.sha256(host.encode()).hexdigest()[:7], 16)


def hold_host(host: str):
    connection = db.engine.connect().execution_options(isolation_level="AUTOCOMMIT")
    if connection.execute(text("SELECT pg_try_advisory_lock(:a, :b)"), {"a": HOST_LOCK, "b": _host_key(host)}).scalar():
        return connection
    connection.close()
    return None


def host_alive(host: str) -> bool:
    with db.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        key = {"a": HOST_LOCK, "b": _host_key(host)}
        if not connection.execute(text("SELECT pg_try_advisory_lock(:a, :b)"), key).scalar():
            return True
        connection.execute(text("SELECT pg_advisory_unlock(:a, :b)"), key)
        return False


# a lock's connection still answers; a probe that fails drops the connection, so a lock it held dies with the session
def lock_held(connection) -> bool:
    try:
        return connection.execute(text("SELECT 1")).scalar() == 1
    except Exception:
        connection.invalidate()
        return False
