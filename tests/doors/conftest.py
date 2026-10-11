import pytest
import settings
from stages import assemble


# runs in door tests never ask the converters for their builds
@pytest.fixture(autouse=True)
def builds(monkeypatch):
    monkeypatch.setattr(assemble, "builds", lambda: {"docling": {"base": "d"}, "mineru": {"base": "m"}})
    monkeypatch.setattr(assemble, "_build", lambda engine: {"base": engine[0]})


@pytest.fixture
def inbox(stand):
    folder = settings.DATA_DIR / "inbox"
    folder.mkdir(parents=True)
    return folder
