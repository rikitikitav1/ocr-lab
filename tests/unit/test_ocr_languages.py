from types import SimpleNamespace

import pytest
import settings
from engines import ocr_languages, reading


@pytest.fixture
def tessdata(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    (tmp_path / "tessdata").mkdir()
    for code in ("eng", "rus"):
        (tmp_path / "tessdata" / f"{code}.traineddata").write_bytes(b"x")
    return tmp_path / "tessdata"


def test_every_installed_book_language_goes_to_docling_in_order_with_english_last(tessdata):
    (tessdata / "fas.traineddata").write_bytes(b"x")
    given = [v for k, v in reading.fields("docling", "text_pdf", ["fa", "ru", "bg"]) if k == "ocr_lang"]
    assert given == ["fas", "rus", "eng"]
    assert not [k for k, _ in reading.fields("mineru", "text_pdf", ["fa"]) if k == "ocr_lang"]


def test_a_language_with_two_data_files_is_installed_only_with_both(tessdata):
    (tessdata / "chi_sim.traineddata").write_bytes(b"x")
    assert not ocr_languages.installed("zh")
    (tessdata / "chi_tra.traineddata").write_bytes(b"x")
    assert ocr_languages.installed("zh") and "zh" in ocr_languages.listing()["installed"]


def test_install_fetches_only_the_missing_files_and_refuses_an_error_page(tessdata, monkeypatch):
    asked = []

    def get(url, **kw):
        asked.append(url)
        body = b"<html>404</html>" if "ara" in url else b"t" * ocr_languages.MIN_BYTES
        return SimpleNamespace(content=body, raise_for_status=lambda: None)

    monkeypatch.setattr(ocr_languages.net, "get", get)
    got = ocr_languages.install("bg")
    assert got["fetched"] == ["bul"] and (tessdata / "bul.traineddata").exists() and len(asked) == 1
    assert ocr_languages.install("ru")["fetched"] == []
    with pytest.raises(RuntimeError):
        ocr_languages.install("ar")
    with pytest.raises(LookupError):
        ocr_languages.install("xx")
