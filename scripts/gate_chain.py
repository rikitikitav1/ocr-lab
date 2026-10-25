# gates a chain of commits one by one on the main tree: fast-forward, reassemble fresh, compare, stop at the first red
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import gate_reassemble

KNOBS = {"assembly.code_from_layer": True, "assembly.mono_paragraphs": True, "assembly.code_union": True,
         "assembly.table_union": True, "assembly.slot_parts": True}


TREE = Path(__file__).resolve().parent.parent


def _git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(TREE), *args], check=True, capture_output=True, text=True).stdout.strip()


def _log(path: Path, line: str) -> None:
    stamped = f"{time.strftime('%H:%M:%S')} {line}"
    print(stamped, flush=True)
    with path.open("a") as f:
        f.write(stamped + "\n")


# a step is green when no book of the runs file moved against the baseline cut to the same books
def _gate(runs: str, out: Path, base: str, knobs: dict, report: Path, ignore: tuple[str, ...]) -> int:
    gate_reassemble.run(runs, str(out), knobs)
    books = json.loads(out.read_text())["books"]
    cut = json.loads(Path(base).read_text())
    cut["books"] = {k: v for k, v in cut["books"].items() if k in books}
    cut_file = out.with_suffix(".base.json")
    cut_file.write_text(json.dumps(cut))
    with report.open("w") as f:
        return gate_reassemble.compare(str(cut_file), str(out), ignore, f)


def main(chain: str, runs: str, base: str, knobs_base: str, out_dir: str, branch: str) -> int:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    log = out / "chain.log"
    steps = [line.split() for line in open(chain) if line.strip() and not line.startswith("#")]
    last: dict[str, str] = {}
    branch = branch or _git("branch", "--show-current")
    if _git("branch", "--show-current") != branch:
        _log(log, f"STOP: the main tree is not on {branch}")
        return 2
    for sha, kind, *rest in steps:
        ignore = tuple(k for r in rest if r.startswith("ignore:") for k in r.removeprefix("ignore:").split(",") if k)
        if _git("status", "--porcelain", "--untracked-files=no"):
            _log(log, "STOP: the main tree has uncommitted changes")
            return 2
        try:
            _git("merge", "--ff-only", "-q", sha)
        except subprocess.CalledProcessError as failed:
            _log(log, f"STOP: {sha[:8]} does not fast-forward: {failed.stderr.strip()}")
            return 2
        _log(log, f"{sha[:8]} {kind}: on {_git('log', '--oneline', '-1')}")
        passes = [("default", base, {})] + ([("knobs", knobs_base, KNOBS)] if kind == "knobs" else [])
        for name, baseline, knobs in passes:
            baseline = last.get(name, baseline)
            try:
                moved = _gate(runs, out / f"{sha[:8]}_{name}.json", baseline, knobs, out / f"{sha[:8]}_{name}.txt",
                              ignore)
            except SystemExit as failed:
                _log(log, f"STOP at {sha[:8]} {name}: {failed.code}")
                return 2
            _log(log, f"{sha[:8]} {name}: {'GREEN' if not moved else 'RED'}, see {sha[:8]}_{name}.txt")
            if moved:
                _log(log, f"STOP at {sha[:8]}; the main tree stays on it")
                return 1
            # the next step answers for its own movers only, so it is compared with this green record
            last[name] = str(out / f"{sha[:8]}_{name}.json")
    _log(log, "DONE: every step green")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("chain", help="one '<commit> default|knobs [ignore:key,key]' per line, in order")
    parser.add_argument("runs", help="the book:run pairs, as gate_reassemble takes them")
    parser.add_argument("--base", default="temp_files/gate0_baseline.json")
    parser.add_argument("--knobs-base", default="temp_files/gate0_knobs.json")
    parser.add_argument("--out", default="temp_files/chain")
    parser.add_argument("--branch", help="the branch the main tree must be on; the one it is on by default")
    # the tree the stand runs; a copy of this script elsewhere still moves that tree
    parser.add_argument("--tree", default=str(TREE))
    args = parser.parse_args()
    TREE = Path(args.tree)
    sys.exit(main(args.chain, args.runs, args.base, args.knobs_base, args.out, args.branch))
