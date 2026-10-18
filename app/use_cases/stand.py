import shutil
import subprocess

import code_version
import httpx
import net
import settings
import worker_registry
from engines import card, converter, ocr_languages
from mcp_tools import tool
from orm.db import Session
from sqlalchemy import text


def _db() -> dict:
    try:
        with Session() as session:
            session.execute(text("SELECT 1"))
            every = worker_registry.workers(session)
        live = {h: w for h, w in every.items() if w["alive"]}
        seen = min((w["seconds_ago"] for w in every.values()), default=None)
        # a worker gone silent stays listed with how long ago it beat, so a dead one is seen, not forgotten
        return {"ok": True, "last_worker_code": worker_registry.worker_code(live), "worker_seen_seconds_ago": seen,
                "workers": {h: {k: v for k, v in w.items() if k != "started_at"} for h, w in every.items()}}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _ollama() -> dict:
    try:
        seen = net.get(settings.OLLAMA_BASE_URL + "/api/version", timeout=3)
        return {"ok": seen.status_code == 200, "version": seen.json().get("version")}
    except httpx.HTTPError as e:
        return {"ok": False, "error": str(e)}


SMI_GPU = ["--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"]
SMI_APPS = ["--query-compute-apps=pid,process_name,used_memory", "--format=csv,noheader,nounits"]
NO_SMI = "no nvidia-smi here: the api container is given no GPU device, and the converters report no memory"


def _smi(smi: str, query: list[str]) -> list[list[str]]:
    done = subprocess.run([smi, *query], capture_output=True, text=True, timeout=5, check=True)
    return [[cell.strip() for cell in line.split(",")] for line in done.stdout.splitlines() if line.strip()]


# what the card holds in memory: ollama's models always, the whole card only where nvidia-smi can see it
def _gpu_memory() -> dict:
    out = {"ollama_models": card.ollama_models()}
    smi = shutil.which("nvidia-smi")
    if smi is None:
        return {**out, "card": None, "card_unseen_because": NO_SMI}
    try:
        used, total = _smi(smi, SMI_GPU)[0][:2]
        processes = [{"pid": int(pid), "name": name, "used_mb": int(mb)} for pid, name, mb in _smi(smi, SMI_APPS)]
    except (subprocess.SubprocessError, OSError, ValueError, IndexError) as e:
        return {**out, "card": None, "card_unseen_because": f"nvidia-smi failed: {e}"}
    return {**out, "card": {"used_mb": int(used), "total_mb": int(total), "processes": processes}}


@tool("stand", "GET /v1/stand",
      "Health of the stand: database and every worker with its code, lanes, CPU-lane threads and last beat (a "
      "silent one stays listed for a day), converters with builds and missing models, ollama, GPU holders and the "
      "card's memory, network sources set aside, and whether a live worker is behind the code on disk (null with "
      "no live worker).")
def stand() -> dict:
    converters = {}
    for name in settings.CONVERTERS:
        state, body = converter.reading(name)
        converters[name] = {"state": state, "build": body.get("build"), "missing_models": body.get("missing_models")}
    db = _db()
    disk_code = code_version.on_disk()
    live = {h: w for h, w in db.get("workers", {}).items() if w["alive"]}
    return {
        "db": db,
        "converters": converters,
        "ollama": _ollama(),
        "gpu_holders": card.holders(),
        "gpu_memory": _gpu_memory(),
        "sources_set_aside": net.inactive(),
        "code": {"api_loaded": code_version.LOADED, "on_disk": disk_code,
                 "worker_last_seen": db.get("last_worker_code"),
                 # each worker keeps its own copy and takes newer code once its lanes empty; no worker seen, null
                 "worker_behind_disk": bool(code_version.behind(live, disk_code)) if live else None},
        "shelf": {"dir": str(settings.SHELF_DIR), "books": (settings.SHELF_DIR / "books").exists(),
                  "gold": (settings.SHELF_DIR / "gold").exists()},
    }


# the book languages Docling's Tesseract has data for, and the ones it could fetch
@tool("ocr_languages", "GET /v1/engines/ocr_languages",
      "The book languages Tesseract has data for in data/tessdata and the ones it could fetch.")
def ocr_language_list() -> dict:
    return ocr_languages.listing()


# fetches the Tesseract data for one book language (ISO 639-1) into data/tessdata; a reading after it uses it
@tool("install_ocr_language", "POST /v1/engines/ocr_languages",
      "Downloads the Tesseract data for one book language (ISO 639-1 code) into data/tessdata, so readings "
      "after it use it.")
def install_ocr_language(language: str) -> dict:
    return ocr_languages.install(language.strip().lower())


# the worker stops claiming and restarts on newer code once its jobs in hand end; a run in flight then mixes code
@tool("reload_worker", "POST /v1/stand/worker/reload",
      "Ask every live worker on older code to take the code on disk once its jobs in hand end, instead of waiting for"
      " an empty queue; a run in flight then mixes code across its pieces. worker_code is the one code they run,"
      " 'mixed' while some are behind.")
def reload_worker() -> dict:
    live, disk = worker_registry.live_workers(), code_version.on_disk()
    behind = code_version.behind(live, disk)
    shown = {h: {k: v for k, v in w.items() if k != "started_at"} for h, w in live.items()}
    seen = {"worker_code": worker_registry.worker_code(live), "on_disk": disk, "workers": shown}
    if not behind:
        return {"requested": False, **seen,
                "because": "no worker seen" if not live else "every worker already runs the code on disk"}
    code_version.request_reload(behind, alive=set(live))
    return {"requested": True, **seen, "asked": behind}
