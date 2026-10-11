import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).parents[2] / "scripts" / "check_links.py"


def _checker():
    spec = importlib.util.spec_from_file_location("check_links", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_broken_links_and_unreferenced_images_are_named(tmp_path):
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "01-001.png").write_bytes(b"png")
    (tmp_path / "images" / "01-002.png").write_bytes(b"png")
    (tmp_path / "book.md").write_text("![](images/01-001.png)\n![](images/01-009.png)\n")
    found = _checker().check(tmp_path)
    assert found["broken"] == ["images/01-009.png"] and found["unreferenced"] == ["images/01-002.png"]
