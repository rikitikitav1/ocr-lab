# HiPS, law books with tables of contents made by people: fetched once at a pinned commit, never committed
import json
from pathlib import Path

import artifacts
import net
import settings
from stages.structure.sources import Entry

REPO = "anybass/HiPS"
COMMIT = "5ca16dd23c8087e4d00569cf05f5c2a456332bc3"
RAW = f"https://raw.githubusercontent.com/{REPO}/{COMMIT}/data"


def folder() -> Path:
    return settings.DATA_DIR / "gold" / "hips" / COMMIT


def fetch() -> list[str]:
    root = folder()
    manifest = root / "manifest.json"
    if manifest.exists():
        return json.loads(manifest.read_text())["books"]
    tree = net.get(f"https://api.github.com/repos/{REPO}/git/trees/{COMMIT}?recursive=1", timeout=60).json()["tree"]
    paths = {t["path"] for t in tree}
    # a gold without its PDF in the repository cannot be scored
    books = sorted(Path(p).stem for p in paths
                   if p.startswith("data/GT_TOCs/") and f"data/PDFs/{Path(p).stem}.pdf" in paths)
    for name in books:
        for kind, ext in (("GT_TOCs", "toc"), ("PDFs", "pdf")):
            target = root / kind / f"{name}.{ext}"
            if not target.exists():
                got = net.get(f"{RAW}/{kind}/{name}.{ext}", timeout=180)
                got.raise_for_status()
                artifacts.atomic_write(target, got.content)
    artifacts.atomic_write(manifest, {"repo": REPO, "commit": COMMIT, "books": books})
    return books


def pdf_path(name: str) -> Path:
    return folder() / "PDFs" / f"{name}.pdf"


# "level,heading,page"; a heading may hold commas, quoted or not, so the level and page are the outer fields
def gold(name: str) -> list[Entry]:
    out = []
    for line in (folder() / "GT_TOCs" / f"{name}.toc").read_text(encoding="utf-8-sig").splitlines():
        parts = line.strip().rstrip(",").split(",")
        # the gold has a few lines without a page; such an entry cannot be placed, so it is not scored
        if len(parts) < 3 or not parts[0].strip().isdigit() or not parts[-1].strip().isdigit():
            continue
        out.append(Entry(",".join(parts[1:-1]).strip().strip('"'), int(parts[0]), int(parts[-1])))
    roots = [e for e in out if e.level == 1]
    # a single entry over the whole book is the book itself, not a node
    if len(roots) == 1 and out and out[0] is roots[0] and len(out) > 1:
        out = out[1:]
    return out
