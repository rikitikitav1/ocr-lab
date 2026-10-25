# byte-identity gate over finished runs: reassemble each fresh, then compare two such records piece by piece
import argparse
import json
import os
import sys
import time
import urllib.request

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
        result = job["result"]
        record["books"][str(book)] = {
            "run": result["run_id"], "job": job_id, "lists": result["book_lists"], "not_kept": result["not_kept"],
            "kept_text_changed": result["kept_text_changed"], "kept_numbers_changed": result["kept_numbers_changed"],
            "pieces": {str(p["ord"]): {"text_sha": p["text_sha"], "images_sha": p["images_sha"], "counts": p["after"]}
                       for p in result["pieces"]}}
        print(book, job_id, len(result["pieces"]), flush=True)
    json.dump(record, open(out, "w"), indent=1, sort_keys=True)


def compare(base_file: str, new_file: str, ignore: tuple[str, ...] = ()) -> int:
    base, new = json.load(open(base_file))["books"], json.load(open(new_file))["books"]
    moved = 0
    for book in sorted(base.keys() | new.keys(), key=int):
        a, b = base.get(book), new.get(book)
        if a is None or b is None:
            print(book, "only in", base_file if b is None else new_file)
            moved += 1
            continue
        lists = sorted(k for k in a["lists"].keys() | b["lists"].keys() if a["lists"].get(k) != b["lists"].get(k))
        text = [o for o in a["pieces"] if o in b["pieces"] and a["pieces"][o]["text_sha"] != b["pieces"][o]["text_sha"]]
        images = [o for o in a["pieces"] if o in b["pieces"]
                  and a["pieces"][o]["images_sha"] != b["pieces"][o]["images_sha"]]
        pieces = sorted(a["pieces"].keys() ^ b["pieces"].keys(), key=int)
        counts: dict[str, int] = {}
        for o in a["pieces"].keys() & b["pieces"].keys():
            x, y = a["pieces"][o]["counts"], b["pieces"][o]["counts"]
            for k in (x.keys() | y.keys()) - set(ignore):
                if x.get(k, "absent") != y.get(k, "absent"):
                    counts[k] = counts.get(k, 0) + 1
        if lists or text or images or pieces or counts:
            moved += 1
            print(book, {"lists": lists, "text": sorted(text, key=int)[:20], "texts": len(text),
                         "images": sorted(images, key=int)[:20],
                         "pieces_apart": pieces, "counts": counts})
    print("books moved:", moved, "of", len(base.keys() | new.keys()))
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
