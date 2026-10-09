import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCES = [p for d in ("app", "tests", "scripts") for p in (ROOT / d).rglob("*.py")]

FORBIDDEN = {
    "commit hash": re.compile(r"\b[0-9a-f]{7,40}\b"),
    "plan section": re.compile(r"\b(section|пункт|арка|arc|MR)\s*\d+(\.\d+)*", re.IGNORECASE),
    "review round": re.compile(r"\b(round|раунд)\s*\d+|\bv\d+\s*#\d+", re.IGNORECASE),
    "date": re.compile(r"\b\d{1,2}\.\d{2}(\.\d{2,4})?\b"),
    "emoji": re.compile(r"[\U0001F300-\U0001FAFF☀-➿]"),
}


def _comments(path: Path):
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if "#" in line:
            yield n, line.split("#", 1)[1]


def test_comments_carry_no_history():
    found = []
    for path in SOURCES:
        if path.name == "test_house_rules.py":
            continue
        for n, comment in _comments(path):
            for what, pattern in FORBIDDEN.items():
                if pattern.search(comment):
                    found.append(f"{path.relative_to(ROOT)}:{n} {what}: {comment.strip()}")
    assert not found, "\n".join(found)
