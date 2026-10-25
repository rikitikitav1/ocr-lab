import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

import settings
from orm.catalogue import Artifact
from orm.db import Session
from sqlalchemy import select


# a short identity of some bytes, as the gates and the artifact keys compare them
def short_sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


@dataclass(frozen=True)
class Owner:
    run_id: int | None = None
    metadata_version_id: int | None = None
    structure_version_id: int | None = None
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


# what an artifact was made from: one key for reuse, and a hash per part so a reader sees which part changed
@dataclass(frozen=True)
class Inputs:
    parts: dict
    stamp: str | None = None

    @property
    def key(self) -> str:
        return self.stamp or input_hash(**self.parts)

    def hashed(self) -> dict:
        return {name: short_sha(canonical(value).encode())
                for name, value in sorted(self.parts.items())}


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


# keyed files go under their inputs' key, so other inputs never replace a file a row vouches for; folder overrides stage
def write(owner: Owner, base: Path, stage: str, name: str, data, inputs: Inputs,
          piece_ord: int | None = None, meta: dict | None = None, heavy: bool = False,
          folder: str | None = None, keyed: bool = False) -> Artifact:
    piece = f"{piece_ord:03d}" if piece_ord is not None else ""
    relative = base / (stage if folder is None else folder) / piece / (inputs.key[:16] if keyed else "") / name
    sha = atomic_write(settings.DATA_DIR / relative, data)
    row = Artifact(**owner.columns(), stage=stage, piece_ord=piece_ord, name=name, path=str(relative),
                   sha256=sha, input_hash=inputs.key, meta={**(meta or {}), "inputs": inputs.hashed()}, heavy=heavy)
    with Session() as session:
        session.add(row)
        session.commit()
    return row


# a hit only when the inputs are the same and the file on disk is still the one recorded
def find_done(owner: Owner, stage: str, name: str, input_hash: str, piece_ord: int | None = None) -> Artifact | None:
    query = select(Artifact).where(Artifact.stage == stage, Artifact.name == name,
                                   Artifact.input_hash == input_hash, Artifact.removed_at.is_(None))
    for column, value in owner.columns().items():
        query = query.where(getattr(Artifact, column) == value)
    query = query.where(Artifact.piece_ord.is_(None) if piece_ord is None else Artifact.piece_ord == piece_ord)
    with Session() as session:
        rows = session.scalars(query.order_by(Artifact.id.desc())).all()
    for row in rows:
        path = settings.DATA_DIR / row.path
        if path.exists() and sha256_file(path) == row.sha256:
            return row
    return None


def directory(relative: Path) -> Path:
    path = settings.DATA_DIR / relative
    path.mkdir(parents=True, exist_ok=True)
    return path


def read(row: Artifact) -> bytes:
    return (settings.DATA_DIR / row.path).read_bytes()
