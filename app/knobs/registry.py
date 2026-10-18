# the knob registry: run knobs from knobs.yaml with defaults from assembly.yaml, book knobs from book_knobs
from functools import cache

import book_knobs
import job_specs
import settings
import yaml
from assembly import passes

RUN_PREFIX = "assembly."


@cache
def _groups() -> dict:
    return yaml.safe_load((settings.CONFIG_DIR / "knobs.yaml").read_text())["groups"]


def registry() -> dict:
    defaults = passes.conf()
    groups = {name: {"question": g["question"],
                     "knobs": {RUN_PREFIX + knob: {**spec, "default": defaults.get(knob), "scope": "run"}
                               for knob, spec in g["knobs"].items()}}
              for name, g in _groups().items()}
    book_defaults = book_knobs.defaults()
    groups["book"] = {"question": "what the metadata and structure stages read before any run",
                      "knobs": {path: {"help": help, "default": book_defaults[path], "scope": "book",
                                       "probe": "the structure and metadata evaluations", "cost": "cpu"}
                                for path, help in book_knobs.KNOBS.items()}}
    return {"groups": groups}


# a bad entry in knobs.yaml fails the start, named, instead of the first run that reads it
def validate() -> dict:
    passes_known = passes.conf()
    bad = []
    for group, g in _groups().items():
        if not g.get("question"):
            bad.append(f"{group}: no question")
        for knob, spec in g["knobs"].items():
            missing = [k for k in ("options", "help", "probe", "cost") if not spec.get(k)]
            if missing:
                bad.append(f"{group}.{knob}: no {', '.join(missing)}")
            if knob not in passes_known:
                bad.append(f"{group}.{knob}: no pass reads it (not in assembly.yaml passes)")
            elif passes_known[knob] not in (spec.get("options") or []):
                bad.append(f"{group}.{knob}: the default {passes_known[knob]!r} is not among {spec.get('options')}")
    if bad:
        raise ValueError("knobs.yaml: " + "; ".join(bad))
    presets()
    return registry()


def run_knobs() -> dict[str, dict]:
    return {path: spec for g in registry()["groups"].values() for path, spec in g["knobs"].items()
            if spec["scope"] == "run"}


def check(values: dict) -> dict:
    known = run_knobs()
    for path, value in values.items():
        if path not in known:
            raise job_specs.Refused(f"unknown run knob {path!r}; known: {sorted(known)}")
        if value not in known[path]["options"]:
            raise job_specs.Refused(f"{path} takes one of {known[path]['options']}, not {value!r}")
    return values


def presets() -> list[dict]:
    out = []
    for path in sorted((settings.CONFIG_DIR / "presets").glob("*.yaml")):
        preset = yaml.safe_load(path.read_text())
        out.append({"name": path.stem, "help": preset["help"], "values": check(preset.get("values") or {}),
                    "choose": preset.get("choose")})
    return out


def preset(name: str) -> dict:
    found = [p for p in presets() if p["name"] == name]
    if not found:
        raise LookupError(f"no preset {name!r}; known: {[p['name'] for p in presets()]}")
    return found[0]
