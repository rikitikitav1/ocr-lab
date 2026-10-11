# counts broken image links and unreferenced files in a bundle directory, wherever it was moved
import json
import re
import sys
from pathlib import Path

LINK = re.compile(r"!\[[^\]]*\]\(([^)\s]+)\)")


def check(bundle: Path) -> dict:
    documents = [p for p in bundle.glob("*.md") if p.name != "report.md"]
    links = {m.group(1) for doc in documents for m in LINK.finditer(doc.read_text())}
    files = {str(p.relative_to(bundle)) for p in (bundle / "images").rglob("*") if p.is_file()}
    return {"documents": [d.name for d in documents], "links": len(links),
            "broken": sorted(link for link in links if not (bundle / link).is_file()),
            "unreferenced": sorted(files - links)}


if __name__ == "__main__":
    found = check(Path(sys.argv[1]))
    print(json.dumps(found, ensure_ascii=False, indent=1))
    sys.exit(1 if found["broken"] or found["unreferenced"] else 0)
