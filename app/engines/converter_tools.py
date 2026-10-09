# one adapter per tool: each speaks its tool's HTTP API and answers in the stand's statuses
import mimetypes
import time
from pathlib import Path

import httpx
import net
from artifacts import sha256_file

from engines import converter

# reads go through net and are retried; posts that start a job are sent once, so a retry never submits twice
POST_TIMEOUT = 120
POLL_WAIT = 10
POLL_TIMEOUT = POLL_WAIT + 30
KEPT = {"success", "partial_success"}
DOCLING_STATUSES = {"success": "success", "partial_success": "partial_success", "failure": "failure",
                    "skipped": "failure"}
MINERU_STATUSES = {"completed": "success", "partial": "partial_success", "failed": "failure",
                   "canceled": "failure"}


def _timeout(started: float, said: str, ceiling: float) -> dict:
    return {"status": "timeout", "tool_status": said, "seconds": round(time.monotonic() - started, 2),
            "errors": [f"no result in {ceiling} s"], "markdown": None, "structure": None}


# submitted, polled, fetched: an hour of conversion is never one open request
def docling(path: Path, fields: list[tuple[str, str]], first: int, last: int, ceiling: float) -> dict:
    base = converter.base_url("docling")
    fields = fields + [("page_range", str(first)), ("page_range", str(last))]
    started = time.monotonic()
    with path.open("rb") as f:
        files = {"files": (path.name, f, mimetypes.guess_type(path.name)[0] or "application/pdf")}
        seen = httpx.post(base + "/v1/convert/file/async", data=fields, files=files, timeout=POST_TIMEOUT)
    seen.raise_for_status()
    task = seen.json()["task_id"]
    deadline = time.monotonic() + ceiling
    while True:
        polled = net.get(f"{base}/v1/status/poll/{task}", params={"wait": POLL_WAIT}, timeout=POLL_TIMEOUT)
        polled.raise_for_status()
        status = polled.json()
        if status["task_status"] in DOCLING_STATUSES:
            break
        if time.monotonic() > deadline:
            return _timeout(started, status["task_status"], ceiling)
    body = {}
    if status["task_status"] != "failure":
        body = net.get(f"{base}/v1/result/{task}", timeout=POST_TIMEOUT).json()
    document = body.get("document") or {}
    said = body.get("status") or status["task_status"]
    stand = DOCLING_STATUSES.get(said, "failure")
    return {"status": stand, "tool_status": said, "seconds": round(time.monotonic() - started, 2),
            "errors": body.get("errors") or [x for x in (status.get("error_message"),) if x],
            "markdown": document.get("md_content") if stand in KEPT else None,
            "structure": document.get("json_content") if stand in KEPT else None}


# an uploaded file lives in the tool's process, so the process start is part of the key
_MINERU_FILES: dict = {}


def _mineru_file(base: str, path: Path, residency) -> str:
    key = (base, residency, str(path), sha256_file(path))
    if key in _MINERU_FILES:
        return _MINERU_FILES[key]
    blob = path.read_bytes()
    up = httpx.post(base + "/v1/uploads", timeout=POST_TIMEOUT, json={
        "filename": path.name, "bytes": len(blob), "purpose": "parse", "sha256sum": key[3],
        "mime_type": mimetypes.guess_type(path.name)[0] or "application/pdf"})
    up.raise_for_status()
    upload = up.json()
    if not (upload.get("file") or {}).get("id"):
        httpx.put(f"{base}/v1/uploads/{upload['id']}/content", content=blob,
                  headers={"Content-Type": "application/octet-stream"}, timeout=POST_TIMEOUT).raise_for_status()
        done = httpx.post(f"{base}/v1/uploads/{upload['id']}/complete", json={"sha256sum": key[3]},
                          timeout=POST_TIMEOUT)
        done.raise_for_status()
        upload = done.json()
    _MINERU_FILES[key] = upload["file"]["id"]
    return _MINERU_FILES[key]


def mineru(path: Path, fields: list[tuple[str, str]], first: int, last: int, ceiling: float) -> dict:
    base = converter.base_url("mineru")
    residency = converter.reading("mineru")[1].get("started_at")
    started = time.monotonic()
    entry = {"source": {"type": "file_id", "file_id": _mineru_file(base, path, residency)},
             "page_range": f"{first}-{last}"}
    posted = httpx.post(base + "/v1/parse/jobs", json={**dict(fields), "files": [entry]}, timeout=POST_TIMEOUT)
    if posted.status_code == 404:
        _MINERU_FILES.clear()
        entry["source"]["file_id"] = _mineru_file(base, path, residency)
        posted = httpx.post(base + "/v1/parse/jobs", json={**dict(fields), "files": [entry]}, timeout=POST_TIMEOUT)
    posted.raise_for_status()
    job = posted.json()["job_id"]
    deadline = time.monotonic() + ceiling
    while True:
        polled = net.get(f"{base}/v1/parse/jobs/{job}", timeout=POST_TIMEOUT)
        polled.raise_for_status()
        state = polled.json()
        if state["status"] in MINERU_STATUSES:
            break
        if time.monotonic() > deadline:
            return _timeout(started, state["status"], ceiling)
        time.sleep(POLL_WAIT / 5)
    result = state["files"][0]
    stand = MINERU_STATUSES.get(result.get("status"), "failure")
    outputs = result.get("output_files") or {}
    markdown = structure = None
    if stand in KEPT:
        if (outputs.get("markdown") or {}).get("file_id"):
            markdown = net.get(f"{base}/v1/files/{outputs['markdown']['file_id']}/content", timeout=POST_TIMEOUT).text
        if (outputs.get("content_list") or {}).get("file_id"):
            structure = net.get(f"{base}/v1/files/{outputs['content_list']['file_id']}/content",
                                  timeout=POST_TIMEOUT).json()
    return {"status": stand, "tool_status": result.get("status"), "seconds": round(time.monotonic() - started, 2),
            "errors": [result["error"]] if result.get("error") else [], "markdown": markdown, "structure": structure}


READ = {"docling": docling, "mineru": mineru}
