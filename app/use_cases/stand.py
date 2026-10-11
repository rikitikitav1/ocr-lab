import shutil
import subprocess

import code_version
import httpx
import net
import settings
from engines import card, converter, ocr_languages
from mcp_tools import tool
from orm.db import Session
from sqlalchemy import text


def _db() -> dict:
    try:
        with Session() as session:
            session.execute(text("SELECT 1"))
            worker = session.execute(text("SELECT code, extract(epoch FROM now() - seen_at) FROM workers "
                                          "ORDER BY seen_at DESC LIMIT 1")).first()
        if worker is None:
            return {"ok": True, "last_worker_code": None, "worker_seen_seconds_ago": None}
        return {"ok": True, "last_worker_code": worker[0], "worker_seen_seconds_ago": round(float(worker[1]))}
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
      "Health of the stand: database and the code the worker runs, converters with builds and missing models, "
      "ollama, GPU holders and the card's memory, network sources set aside, and whether the worker is behind the "
      "code on disk.")
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
        "gpu_memory": _gpu_memory(),
        "sources_set_aside": net.inactive(),
        "code": {"api_loaded": code_version.LOADED, "on_disk": disk_code,
                 "worker_last_seen": db.get("last_worker_code"),
                 # the worker keeps its own copy and takes the newer code once the queue is empty
                 "worker_behind_disk": db.get("last_worker_code") not in (None, disk_code)},
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
