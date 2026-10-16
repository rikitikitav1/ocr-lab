# a run's profile: every run knob's value with where it came from, immutable and named by its hash
import hashlib
import json

from knobs import registry
from orm.catalogue import Profile
from orm.db import Session
from sqlalchemy import select

# until profile search is built a run says it skipped it, in its start answer and in its report
SEARCH_SKIPPED = "skipped: profile search is not built"

def _sha(preset: str, values: dict, piece_overrides: dict) -> str:
    body = json.dumps({"preset": preset, "values": {k: v["value"] for k, v in values.items()},
                       "chapters": piece_overrides}, sort_keys=True)
    return hashlib.sha256(body.encode()).hexdigest()


def view(profile: Profile) -> dict:
    return {"id": profile.id, "book_id": profile.book_id, "preset": profile.preset, "sha256": profile.sha256,
            "parent_id": profile.parent_id, "values": profile.values, "piece_overrides": profile.piece_overrides,
            "created_at": profile.created_at}


# the same values for the same book are one profile, so runs on unchanged defaults share it
def _stored(session, book_id: int, preset: str, values: dict, piece_overrides: dict,
            parent_id: int | None) -> Profile:
    sha = _sha(preset, values, piece_overrides)
    found = session.scalar(select(Profile).where(Profile.book_id == book_id, Profile.sha256 == sha))
    if found is not None:
        return found
    profile = Profile(book_id=book_id, preset=preset, values=values, piece_overrides=piece_overrides,
                      sha256=sha, parent_id=parent_id)
    session.add(profile)
    session.flush()
    return profile


def resolve(session, book_id: int, preset: str = "default") -> Profile:
    chosen = registry.preset(preset)
    values = {}
    for path, spec in registry.run_knobs().items():
        if path in chosen["values"]:
            values[path] = {"value": chosen["values"][path], "source": "preset", "evidence": f"preset {preset}"}
        else:
            values[path] = {"value": spec["default"], "source": "preset", "evidence": "registry default"}
    return _stored(session, book_id, preset, values, {}, None)


def derive(id: int, set: dict | None = None, pieces: dict | None = None) -> dict:
    with Session() as session:
        parent = session.get(Profile, id)
        if parent is None:
            raise LookupError(f"no profile {id}")
        values = dict(parent.values)
        for path, value in registry.check(set or {}).items():
            values[path] = {"value": value, "source": "manual", "evidence": f"derived from profile {id}"}
        overrides = dict(parent.piece_overrides)
        for ord, knobs in (pieces or {}).items():
            overrides[str(ord)] = {**overrides.get(str(ord), {}), **registry.check(knobs)}
        profile = _stored(session, parent.book_id, parent.preset, values, overrides, parent.id)
        session.commit()
        return view(profile)


def get(id: int) -> dict:
    with Session() as session:
        profile = session.get(Profile, id)
        if profile is None:
            raise LookupError(f"no profile {id}")
        return view(profile)


# the pass switches one piece assembles with: the profile's values under the piece's own overrides
def passes_for(values: dict, piece_overrides: dict, ord: int) -> dict:
    out = {path.removeprefix(registry.RUN_PREFIX): v["value"] for path, v in values.items()}
    out.update({path.removeprefix(registry.RUN_PREFIX): v for path, v in piece_overrides.get(str(ord), {}).items()})
    return out

