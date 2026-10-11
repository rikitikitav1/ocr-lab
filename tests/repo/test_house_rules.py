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


def test_a_comment_is_one_line():
    found = []
    for path in SOURCES + list((ROOT / "config").rglob("*.yaml")):
        lines = path.read_text(encoding="utf-8").splitlines()
        for n, (line, after) in enumerate(zip(lines, lines[1:], strict=False), 1):
            if line.lstrip().startswith("#") and after.lstrip().startswith("#") and not line.startswith("#!"):
                found.append(f"{path.relative_to(ROOT)}:{n}")
    assert not found, "comments longer than one line:\n" + "\n".join(found)


SPEC_REFERENCE = re.compile(r"\b(?:FR|SC)-\d{3}\b|\bT\d{3}\b|\bUS\d\b|\bPrinciple [IVX]+\b")


# code says what it does and why; requirement, task and principle numbers belong to the spec, not the source
def test_code_names_no_spec_numbers():
    found = []
    for path in SOURCES + list((ROOT / "config").rglob("*.yaml")) + list((ROOT / "scripts").glob("*.sh")):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if SPEC_REFERENCE.search(line):
                found.append(f"{path.relative_to(ROOT)}:{n}: {line.strip()[:80]}")
    assert not found, "spec numbers in code:\n" + "\n".join(found)


DOORS = {"pdf.py", "engines/converter_tools.py", "models_client.py"}
STAGES = ("stages", "evaluation", "job_handlers")
RAW = re.compile(r"^\s*(?:import|from)\s+(pypdfium2|httpx|openai|text_clean)\b", re.MULTILINE)


# text enters the stand only through its doors, each cleans it, so no stage reads a raw PDF, engine or model
def test_text_enters_only_through_the_doors():
    app = ROOT / "app"
    found = []
    for path in app.rglob("*.py"):
        name = str(path.relative_to(app))
        if name in DOORS or name == "text_clean.py":
            continue
        for m in RAW.finditer(path.read_text(encoding="utf-8")):
            if m.group(1) == "text_clean" or name.startswith(STAGES):
                found.append(f"{name}: {m.group(1)}")
    assert not found, found


GOLD_FREE = ("stages", "rules", "probes", "assembly")
GOLD_TOUCH = re.compile(r"^\s*(?:import|from)\s+evaluation\b|SHELF_DIR\s*/\s*[\"']gold", re.MULTILINE)


# the assembler decides from the book alone; a gold set only measures it from outside
def test_no_gold_reaches_the_assembly():
    app = ROOT / "app"
    found = [str(p.relative_to(app)) for d in GOLD_FREE for p in (app / d).rglob("*.py")
             if GOLD_TOUCH.search(p.read_text(encoding="utf-8"))]
    assert not found, found
