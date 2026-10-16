# the knob registry, the presets and the profiles runs are made with
import profiles
from knobs import registry
from mcp_tools import tool


@tool("knobs", "GET /v1/knobs",
      "Every knob by group with the question it answers: options, help, default, scope (run or book), cost and "
      "the probe that measures it.")
def knobs() -> dict:
    return registry.registry()


@tool("presets", "GET /v1/presets",
      "The knob presets with their help and values.")
def presets() -> list[dict]:
    return registry.presets()


@tool("profile", "GET /v1/profiles/{id}",
      "One profile: knob values with source and evidence, and per-piece overrides.")
def profile(id: int) -> dict:
    return profiles.get(id)


# a new profile from an existing one; `pieces` maps a piece's ord to its own knob values
@tool("derive_profile", "POST /v1/profiles/{id}/derive",
      "Makes a new profile from an existing one with `set` knob values and per-piece overrides (`pieces` "
      "maps a piece ord to knob values); the same values give the existing profile.")
def derive_profile(id: int, set: dict | None = None, pieces: dict[str, dict] | None = None) -> dict:
    return profiles.derive(id, set, pieces)
