# a throwaway database per test module, built from the schema dump
import os
import uuid

import pytest
from sqlalchemy import create_engine, make_url, text

SCHEMA = os.path.join(os.path.dirname(__file__), "..", "db", "schema.sql")
ADMIN = os.getenv("TEST_POSTGRES_URL", "postgresql+psycopg://postgres@localhost:5433/postgres")


def _reachable() -> bool:
    probe = create_engine(ADMIN, connect_args={"connect_timeout": 3})
    try:
        probe.connect().close()
        return True
    except Exception:
        return False
    finally:
        probe.dispose()


needs_db = pytest.mark.skipif(
    not _reachable(), reason=f"no postgres at {ADMIN}; start the stand or set TEST_POSTGRES_URL"
)


def scratch():
    name = f"ocrtest_{uuid.uuid4().hex[:12]}"
    admin = create_engine(ADMIN, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'CREATE DATABASE "{name}"'))
    engine = create_engine(make_url(ADMIN).set(database=name))
    with engine.begin() as c:
        c.execute(text(_loadable(open(SCHEMA, encoding="utf-8").read())))
    # the dump empties search_path for its session, and the pool would hand that session on
    engine.dispose()
    yield engine
    engine.dispose()
    with admin.connect() as c:
        c.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
    admin.dispose()


# pg_dump writes psql meta-commands the driver cannot run
def _loadable(dump: str) -> str:
    return "\n".join(x for x in dump.splitlines() if not x.startswith("\\"))
