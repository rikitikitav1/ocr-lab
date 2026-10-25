# byte-identity gate over finished runs: reassemble each fresh, then compare two such records piece by piece
import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
from evaluation import byte_gate  # noqa: E402

API = os.getenv("OCR_LAB_API", "http://localhost:8100/v1")
WAIT = 300


def _call(path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(f"{API}{path}", data=data, method="POST" if data is not None else "GET",
                                     headers={"content-type": "application/json"})
    with urllib.request.urlopen(request, timeout=WAIT + 30) as response:
        return json.load(response)


# a gate over code the worker has not loaded measures the old code; with no live worker the state is None, so it waits
def _worker_on_disk() -> None:
    _call("/stand/worker/reload", {})
    for _ in range(60):
        if _call("/stand")["code"]["worker_behind_disk"] is False:
            return
        time.sleep(10)
    sys.exit("the worker did not load the code on disk")


def _runs(path: str) -> list[tuple[int, int]]:
    return [tuple(map(int, pair.split(":"))) for pair in open(path).read().split()]


def run(runs_file: str, out: str, knobs: dict) -> None:
    _worker_on_disk()
    jobs = {book: _call(f"/runs/{run_id}/reassemble", {"knobs": knobs, "fresh": True})["job_id"]
            for book, run_id in _runs(runs_file)}
    record = {"knobs": knobs, "books": {}}
    for book, job_id in jobs.items():
        while not (job := _call(f"/jobs/{job_id}/wait?timeout={WAIT}")).get("finished"):
            pass
        job = _call(f"/jobs/{job_id}")
        if job["status"] != "done":
            sys.exit(f"book {book} job {job_id}: {job['status']} {job.get('error')}")
        record["books"][str(book)] = byte_gate.entry(job_id, job["result"])
        print(book, job_id, len(job["result"]["pieces"]), flush=True)
    json.dump(record, open(out, "w"), indent=1, sort_keys=True)


def compare(base_file: str, new_file: str, ignore: tuple[str, ...] = (), out=None) -> int:
    moved, lines = byte_gate.compare(json.load(open(base_file))["books"], json.load(open(new_file))["books"], ignore)
    print("\n".join(lines), file=out or sys.stdout)
    return 1 if moved else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    record = commands.add_parser("run", help="reassemble each book:run of the file fresh and keep the record")
    record.add_argument("runs")
    record.add_argument("out")
    # with knobs each piece is assembled twice (before and after), so a knob pass takes about twice as long
    record.add_argument("--knobs", default="{}", help='as the reassemble door takes them, {"assembly.<knob>": value}')
    against = commands.add_parser("compare", help="text, book-level lists and counts of two records")
    against.add_argument("base")
    against.add_argument("new")
    # counts a change is meant to move, named so that nothing else may move unseen
    against.add_argument("--ignore", default="", help="comma-separated count keys left out of the compare")
    args = parser.parse_args()
    if args.command == "run":
        run(args.runs, args.out, json.loads(args.knobs))
    else:
        sys.exit(compare(args.base, args.new, tuple(k for k in args.ignore.split(",") if k)))
