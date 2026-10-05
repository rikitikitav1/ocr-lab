import code_version
import httpx
import net
import settings
from engines import card, converter
from mcp_tools import tool
from orm.db import Session
from orm.jobs import Job
from sqlalchemy import func, select, text


def _db() -> dict:
    try:
        with Session() as session:
            session.execute(text("SELECT 1"))
            worker = session.execute(select(Job.code_hash, func.max(Job.updated_at))
                                     .where(Job.code_hash.is_not(None)).group_by(Job.code_hash)
                                     .order_by(func.max(Job.updated_at).desc()).limit(1)).first()
        return {"ok": True, "last_worker_code": worker[0] if worker else None}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _ollama() -> dict:
    try:
        seen = net.get(settings.OLLAMA_BASE_URL + "/api/version", timeout=3)
        return {"ok": seen.status_code == 200, "version": seen.json().get("version")}
    except httpx.HTTPError as e:
        return {"ok": False, "error": str(e)}


@tool("stand", "GET /v1/stand")
def stand() -> dict:
    converters = {}
    for name in settings.CONVERTERS:
        state, body = converter.reading(name)
        converters[name] = {"state": state, "build": body.get("build"), "missing_models": body.get("missing_models")}
    db = _db()
    disk_code = code_version.tree_hash()
    return {
        "db": db,
        "converters": converters,
        "ollama": _ollama(),
        "gpu_holders": card.holders(),
        "sources_set_aside": net.inactive(),
        "code": {"api_loaded": code_version.LOADED, "on_disk": disk_code,
                 "worker_last_seen": db.get("last_worker_code"),
                 "worker_differs_from_disk": db.get("last_worker_code") not in (None, disk_code)},
        "shelf": {"dir": str(settings.SHELF_DIR), "books": (settings.SHELF_DIR / "books").exists(),
                  "gold": (settings.SHELF_DIR / "gold").exists()},
    }
