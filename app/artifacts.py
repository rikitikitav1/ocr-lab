import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

import settings
from orm.catalogue import Artifact
from orm.db import Session
from sqlalchemy import select


@dataclass(frozen=True)
class Owner:
    run_id: int | None = None
    metadata_version_id: int | None = None
    toc_version_id: int | None = None
    book_id: int | None = None

    def columns(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v is not None}


def book_dir(book_id: int) -> Path:
    return Path("books") / str(book_id)


def version_dir(book_id: int, kind: str, version: int) -> Path:
    return book_dir(book_id) / kind / f"v{version}"


def run_dir(book_id: int, run_id: int) -> Path:
    return Path("runs") / str(book_id) / str(run_id)


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def input_hash(**parts) -> str:
    return hashlib.sha256(canonical(parts).encode()).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _bytes(data) -> bytes:
    if isinstance(data, bytes):
        return data
    if isinstance(data, str):
        return data.encode()
    return json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True, default=str).encode()


# written aside and renamed, so a crash never leaves a half file that a manifest row vouches for
def atomic_write(path: Path, data) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    blob = _bytes(data)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("wb") as f:
        f.write(blob)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    return hashlib.sha256(blob).hexdigest()


def write(owner: Owner, base: Path, stage: str, name: str, data, input_hash: str,
          chapter_ord: int | None = None, meta: dict | None = None, heavy: bool = False) -> Artifact:
    relative = base / stage / (f"{chapter_ord:03d}" if chapter_ord is not None else "") / name
    sha = atomic_write(settings.DATA_DIR / relative, data)
    row = Artifact(**owner.columns(), stage=stage, chapter_ord=chapter_ord, name=name, path=str(relative),
                   sha256=sha, input_hash=input_hash, meta=meta or {}, heavy=heavy)
    with Session() as session:
        session.add(row)
        session.commit()
    return row


# a hit only when the inputs are the same and the file on disk is still the one recorded
def find_done(owner: Owner, stage: str, name: str, input_hash: str, chapter_ord: int | None = None) -> Artifact | None:
    query = select(Artifact).where(Artifact.stage == stage, Artifact.name == name,
                                   Artifact.input_hash == input_hash, Artifact.removed_at.is_(None))
    for column, value in owner.columns().items():
        query = query.where(getattr(Artifact, column) == value)
    query = query.where(Artifact.chapter_ord.is_(None) if chapter_ord is None else Artifact.chapter_ord == chapter_ord)
    with Session() as session:
        rows = session.scalars(query.order_by(Artifact.id.desc())).all()
    for row in rows:
        path = settings.DATA_DIR / row.path
        if path.exists() and sha256_file(path) == row.sha256:
            return row
    return None


def read(row: Artifact) -> bytes:
    return (settings.DATA_DIR / row.path).read_bytes()
