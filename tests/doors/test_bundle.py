import importlib.util
import json
import re
import shutil
from pathlib import Path

import settings
from quality import book as book_quality
from stages import bundle
from stages.structure import collect

from tests.doors.test_runs import TEXT, _drain, engines
from tests.fixtures import build, text_page
from tests.real_db import needs_db

pytestmark = needs_db
CONTRACT = Path(__file__).parents[2] / "specs" / "001-pdf-book-to-markdown" / "contracts" / "bundle.md"
SCRIPT = Path(__file__).parents[2] / "scripts" / "check_links.py"


def _schema() -> dict:
    return json.loads(re.search(r"## report.json \(schema 3\).*?```json\n(.*?)```", CONTRACT.read_text(), re.S)[1])


# every key the contract's example names is in the report; an empty example object ({}) is free-form
def _missing(want, got, path="") -> list[str]:
    out = []
    if isinstance(want, dict) and want:
        for key, value in want.items():
            if not isinstance(got, dict) or key not in got:
                out.append(f"{path}.{key}")
            else:
                out += _missing(value, got[key], f"{path}.{key}")
    elif isinstance(want, list) and want and isinstance(want[0], dict) and got:
        out += _missing(want[0], got[0], f"{path}[0]")
    return out


# every key the report has is named in the contract's example, so a new key cannot ship unwritten
def _unnamed(got, want, path="") -> list[str]:
    out = []
    if isinstance(got, dict) and isinstance(want, dict) and want:
        for key, value in got.items():
            out += [f"{path}.{key}"] if key not in want else _unnamed(value, want[key], f"{path}.{key}")
    elif isinstance(got, list) and isinstance(want, list) and got and want and isinstance(want[0], dict):
        out += _unnamed(got[0], want[0], f"{path}[0]")
    return out


def test_the_key_check_names_a_key_the_report_lacks():
    assert _missing({"a": {"b": 0, "c": {}}, "d": [{"e": 0}]}, {"a": {"c": {"x": 1}}, "d": [{}]}) == [".a.b", ".d[0].e"]


def test_the_key_check_names_a_key_the_contract_does_not():
    assert _unnamed({"a": {"b": 0, "c": {"x": 1}}, "d": [{"e": 0, "f": 1}]},
                    {"a": {"b": 0, "c": {}}, "d": [{"e": 0}]}) == [".d[0].f"]


# a plain book (no code, formulas, verse or pictures) under the default preset gets every field and clean links
def test_a_plain_book_s_bundle_carries_the_contract_s_report_and_survives_a_move(client, inbox, monkeypatch, tmp_path):
    pages = [text_page("One", TEXT, bookmark="One"), text_page("Two", TEXT, bookmark="Two")]
    book = client.post("/v1/books", json={"file_paths": [str(build(inbox / "plain.pdf", pages))], "then": []}).json()
    collect.collect(book["id"])

    engines(monkeypatch)
    run_id = client.post(f"/v1/books/{book['id']}/runs", json={}).json()["run"]["id"]
    _drain()
    bundle = settings.DATA_DIR / client.get(f"/v1/runs/{run_id}").json()["bundle_dir"]
    report = json.loads((bundle / "report.json").read_text())
    assert report["schema"] == 3 and _missing(_schema(), report) == [] and _unnamed(report, _schema()) == []
    assert report["profile"]["preset"] == "default" and (bundle / "profile.yaml").exists()
    assert (bundle / "images").is_dir() and report["metadata"]["structure_sources"]["base"] == "bookmarks"
    nodes = json.loads((bundle / "structure.json").read_text())
    assert nodes and all(n["unit"] is not None for n in nodes if n["pinned"])
    assert sum(v["nodes"] for v in report["numbers"]["nodes_by_level"].values()) == len(nodes)
    assert (report["numbers"]["blocks_without_node"], report["numbers"]["blocks_in_two"]) == (0, 0)
    assert report["metadata"]["fields"] == {} and report["pieces"][0]["files"][0]["file"] == 0
    moved = shutil.copytree(bundle, tmp_path / "moved")
    spec = importlib.util.spec_from_file_location("check_links", SCRIPT)
    links = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(links)
    found = links.check(moved)
    assert found["documents"] == ["plain.md"] and found["broken"] == [] and found["unreferenced"] == []


def test_report_md_reads_lists_as_text_a_book_without_pages_as_n_a_and_names_only_deep_chapters():
    numbers = book_quality.numbers([{"ord": 1, "title": "One", "status": "done",
                                     "checks": {"title_level": 2, "max_heading_level": 6}},
                                    {"ord": 2, "title": "Two", "status": "done",
                                     "checks": {"title_level": 2, "max_heading_level": 4}}], [])
    report = {"book": {"title": "Book"}, "images": {"figures": 0, "files": 0, "broken_links": 0},
              "numbers": {**numbers, "pages_cut": {"contents": [3, 4], "cover": []}},
              "languages": {"book": ["en", "ru"], "ocr": ["eng", "rus"], "missing": []},
              "seconds": {"read": {"docling": 0.0}, "readings_untimed": 0, "assemble": 0.0, "pages": 0,
                          "per_page": {}},
              "metadata": {"fields": {"authors": {"value": ["Ann", "Bob"], "source": "isbn", "confidence": 1}}},
              "pieces": []}
    text = bundle._summary(report)
    assert "| languages / OCR data / missing | en, ru / eng, rus / none |" in text
    assert "| pages cut: printed contents / cover | 3, 4 / none |" in text
    assert "reading n/a, assembly n/a" in text and "None" not in text and "[" not in text
    assert "- authors: Ann, Bob (isbn)" in text
    assert "- 1 One: level 6" in text and "- 2 Two" not in text
