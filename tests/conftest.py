import pytest

from tests.real_db import scratch


@pytest.fixture(scope="module")
def db():
    yield from scratch()


# points the stand's session, the LISTEN connection and the data dir at throwaway places
@pytest.fixture
def stand(db, tmp_path, monkeypatch):
    import settings
    from orm import db as orm_db

    monkeypatch.setattr(settings, "DATABASE_URL", db.url.render_as_string(hide_password=False))
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    previous = orm_db.engine
    orm_db.bind(db)
    yield db
    orm_db.bind(previous)


# a client always talks to the throwaway database, so a test can never write into the stand's own
@pytest.fixture
def client(stand):
    from fastapi.testclient import TestClient
    from server import app

    with TestClient(app) as c:
        yield c
