# a run's piece put together from its kept readings, and the inputs that tell whether a done piece must be made again
import hashlib
import json

import artifacts
import code_version
import profiles
from assembly import passes
from orm.catalogue import Artifact, Profile, Run
from orm.db import Session
from quality import piece as piece_quality
from sqlalchemy import select

from stages import assemble, run_pieces, run_state


# what made the piece: structure version, the profile's values, languages, the code, the builds that read it, the passes
def piece_inputs(run: Run, profile: Profile | None, ord: int, knobs: dict, builds: dict,
                   languages: list[str], code: str | None = None) -> artifacts.Inputs:
    return artifacts.Inputs({"stage": "assemble", "run": run.id, "ord": ord,
                             "structure_version": run.structure_version_id,
                             "profile": profile.sha256 if profile is not None else None,
                             "languages": languages, "code": code or code_version.LOADED, "builds": builds,
                             "passes": hashlib.sha256(json.dumps(knobs, sort_keys=True).encode()).hexdigest()[:16],
                             # a run cut by parts and pieces, or started before runs held a layout, keeps its inputs
                             **({"reading_level": run.reading_level} if run.reading_level is not None else {}),
                             **({"layout": run.layout_version_id} if run.layout_version_id is not None else {})})


# a done piece whose kept assembly was made from other inputs than the code on disk would use is assembled again
def piece_changed(session, run: Run, ord: int) -> bool:
    kept = session.scalar(select(Artifact.input_hash).where(
        Artifact.run_id == run.id, Artifact.stage == "assemble", Artifact.piece_ord == ord,
        Artifact.name == "model.json", Artifact.removed_at.is_(None)).order_by(Artifact.id.desc()).limit(1))
    if kept is None:
        return True
    return _inputs(session, run, ord, code=code_version.on_disk())[0].key != kept


# a piece's inputs as its assembly would take them now, with the knobs, readings, builds and languages behind them
def _inputs(session, run: Run, ord: int, overrides: dict | None = None, code: str | None = None) -> tuple:
    profile = session.get(Profile, run.profile_id) if run.profile_id is not None else None
    knobs = {**_knobs(profile, ord), **(overrides or {})}
    readings, builds = run_state.round_readings(session, run.id, ord)
    languages = assemble.languages_in(run.metadata_version_id)
    return piece_inputs(run, profile, ord, knobs, builds, languages, code), knobs, readings, builds, languages


# a run without a profile (one started before profiles) assembles on the passes' config
def _knobs(profile: Profile | None, ord: int) -> dict:
    if profile is None:
        return dict(passes.conf())
    return profiles.passes_for(profile.values, profile.piece_overrides, ord)


# a piece meets its neighbours on its first and last pages; a run cut by parts and pieces cuts as it always did
def _boundaries(entry: dict) -> list[passes.Boundary] | None:
    if not entry.get("piece"):
        return None
    return [*([passes.Boundary(entry["first_page"], entry["title"], False)] if entry["shared_start"] else []),
            *([passes.Boundary(entry["last_page"], entry["next_title"], True)] if entry["next_title"] else [])]


# a re-read boundary page is the next piece's own; the tail the earlier piece took off it is that piece's alone
def measured_layer(entry: dict, layer: dict[int, str], boundaries: list[dict]) -> dict[int, str]:
    tails = {r["page"]: r.get("tail_text", "") for r in boundaries if r.get("read")}
    out = dict(layer)
    first, last = entry["first_page"], entry["last_page"]
    if entry.get("reread_end") and last in out:
        out[last] = tails.get(last, "")
    if entry.get("reread_start") and first in out and tails.get(first):
        rest = piece_quality.words(out[first]) - piece_quality.words(tails[first])
        out[first] = " ".join(rest.elements())
    return out


# a piece put together from this round's kept readings; `overrides` go over the profile's passes and touch nothing
def assembled(run_id: int, ord: int, overrides: dict | None = None, level: int | None = None,
              reread: bool = True) -> tuple[assemble.Assembled, dict, dict]:
    with Session() as session:
        run = session.get(Run, run_id)
        entry = run_pieces.piece_entry(session, run, ord, level, reread)
        made_from, knobs, readings, builds, languages = _inputs(session, run, ord, overrides)
        # a piece takes its tail on the page the next one opens on from the next one's reading of it
        neighbour = run_state.round_readings(session, run_id, entry["next_ord"])[0] \
            if entry.get("piece") and entry.get("next_ord") is not None else None
        book_id, base = run.book_id, artifacts.run_dir(run.book_id, run_id)
        cut = run_pieces.all_cut(session, run)
        versions = assemble.Pinned(run.layout_version_id, run.structure_version_id)
    got = assemble.assemble(book_id, ord, entry["title"], entry["level"], entry["first_page"], entry["last_page"],
                            entry["subs"], languages, cut=cut, role=entry["role"], knobs=knobs, readings=readings,
                            shared_start=entry["shared_start"], next_title=entry["next_title"],
                            nodes=entry["nodes"], piece=entry.get("piece", False),
                            reread_end=entry.get("reread_end", False), boundaries=_boundaries(entry),
                            neighbour=neighbour, versions=versions)
    reread_start, reread_end = entry.get("reread_start", False), entry.get("reread_end", False)
    shared = frozenset([entry["first_page"]] * (entry["shared_start"] and not reread_start)
                       + [entry["last_page"]] * (bool(entry["next_title"]) and not reread_end))
    layer = measured_layer(entry, got.layer, got.boundaries)
    recognised = {p: s for p, s in got.recognised.items() if not (reread_end and p == entry["last_page"])}
    # a caption on a shared page is measured by neither piece, on a re-read page by the piece that owns it
    captions = {p: c for p, c in got.captions.items()
                if p not in shared and not (reread_end and p == entry["last_page"])}
    checks = piece_quality.check(got.piece, entry["subs"], layer, got.furniture, recognised, shared, languages,
                                 captions)
    return got, checks, {"base": base, "made_from": made_from, "builds": builds, "languages": languages}
