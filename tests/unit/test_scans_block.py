import json
from types import SimpleNamespace

from stages import bundle


def test_recognised_pages_group_by_engine_with_agreement_and_dictionary_share(monkeypatch):
    pages = {"3": {"picked": "mineru", "agreement": 0.9}, "4": {"picked": "mineru", "agreement": 0.7},
             "5": {"picked": "docling", "agreement": 0.8}, "6": {"picked": "docling", "scores": {}}}
    model = {"ord": 1, "title": "One", "level": 1, "first_page": 3, "last_page": 6, "blocks": [
        {"type": "page", "book_page": 3, "file_ord": 0, "file_page": 1}, {"type": "paragraph", "text": "the house"},
        {"type": "page", "book_page": 4, "file_ord": 0, "file_page": 2}, {"type": "paragraph", "text": "qzxv"},
        {"type": "page", "book_page": 5, "file_ord": 0, "file_page": 3}, {"type": "paragraph", "text": "water"}]}
    kept = {"pages.json": pages, "model.json": model}
    monkeypatch.setattr(bundle, "_newest", lambda session, run_id, ord, name: SimpleNamespace(name=name))
    monkeypatch.setattr(bundle.artifacts, "read", lambda row: json.dumps(kept[row.name]).encode())
    files = [SimpleNamespace(ord=0, first_page=3, pages=4)]
    got = bundle._scans(None, SimpleNamespace(id=1), [SimpleNamespace(ord=1)], files, ["en"])
    assert [(s["pages"], s["engine"], s["file_pages"]) for s in got] == [([3, 4], "mineru", [1, 2]),
                                                                          ([5, 5], "docling", [3, 3])]
    assert got[0]["agreement"] == 0.8 and got[0]["agreement_min"] == 0.7 and got[0]["engine_confidence"] is None
    assert got[0]["dictionary_words"] == 3 and got[0]["dictionary_share"] == round(2 / 3, 3)
    assert bundle._scans(None, SimpleNamespace(id=1), [SimpleNamespace(ord=1)], files, ["zh"])[0]["dictionary_share"] \
        is None
