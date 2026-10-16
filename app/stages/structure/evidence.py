# the structure version's sources.json, written by collect: every source's raw list and the one chosen as the base
import json

import artifacts
from orm.catalogue import Artifact
from sqlalchemy import select


def read(session, structure_version_id: int) -> dict | None:
    row = session.scalar(select(Artifact).where(Artifact.structure_version_id == structure_version_id,
                                                Artifact.name == "sources.json"))
    return json.loads(artifacts.read(row)) if row is not None else None


def base(session, structure_version_id: int) -> str | None:
    return (read(session, structure_version_id) or {}).get("chosen")
