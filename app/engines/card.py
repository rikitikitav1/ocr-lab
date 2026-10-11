# one GPU for every engine: a handover releases the others before the target takes it
import time

import httpx
import job_queue
import logging_setup
import net
import settings

from engines import converter

log = logging_setup.get_logger(__name__)

WAIT_CEILING = 120
POLL_SECONDS = 0.5
OLLAMA = "ollama"


class CardNotHanded(RuntimeError):
    pass


# the card belongs to the GPU lane: a CPU job that needs it hands its work to a GPU job instead
class WrongLane(RuntimeError):
    pass


# the models ollama keeps loaded, with the card memory each takes
def ollama_models() -> list[dict]:
    try:
        seen = net.get(settings.OLLAMA_BASE_URL + "/api/ps", timeout=5)
        seen.raise_for_status()
        return [{"name": m["name"], "vram_mb": round((m.get("size_vram") or 0) / 2**20)}
                for m in seen.json().get("models", [])]
    except httpx.HTTPError:
        return []


def _ollama_loaded() -> list[str]:
    return [m["name"] for m in ollama_models()]


def _ollama_unload(model: str) -> None:
    net.post(settings.OLLAMA_BASE_URL + "/api/generate", json={"model": model, "keep_alive": 0}, timeout=60)


# read from the servers each time: a table of holders would drift from them
def holders() -> list[str]:
    held = [name for name in settings.CONVERTERS if converter.reading(name)[0] == converter.HOLDS]
    if _ollama_loaded():
        held.append(OLLAMA)
    return held


def hand_to(target: str) -> None:
    # only a job on the GPU lane takes the card: a CPU job, a door or a script outside the worker never does
    if job_queue.running_lane.get() != "gpu":
        raise WrongLane(f"{target} is needed, and the card is taken only on the GPU lane")
    try:
        _hand_to(target)
    except net.SourceDown as e:
        raise CardNotHanded(f"{target}: {e}") from e


def _hand_to(target: str) -> None:
    before = holders()
    for name in before:
        if name == target:
            continue
        if name == OLLAMA:
            for model in _ollama_loaded():
                _ollama_unload(model)
            _until(lambda: not _ollama_loaded(), "ollama did not unload its models")
        else:
            converter.let_go(name)
            _until(lambda n=name: converter.reading(n)[0] != converter.HOLDS, f"{name} did not let go")
    if target != OLLAMA:
        state = converter.reading(target)[0]
        if state in (converter.DOWN, converter.UNKNOWN):
            raise CardNotHanded(f"{target} is {state}; the card stays where it is")
        try:
            _until(lambda: converter.take_once(target), f"{target} did not get ready")
        except converter.WillNotStart as e:
            raise CardNotHanded(str(e)) from e
    left = [h for h in holders() if h != target]
    if left:
        raise CardNotHanded(f"{target} took the card and {', '.join(left)} still hold it")
    # a target that already held the card alone is no handover, so only a real change is logged
    if before != [target]:
        log.info("card.handed", engine=target, released=[h for h in before if h != target])


def _until(done, why: str) -> None:
    deadline = time.monotonic() + WAIT_CEILING
    while time.monotonic() < deadline:
        if done():
            return
        time.sleep(POLL_SECONDS)
    raise CardNotHanded(f"{why} in {WAIT_CEILING}s")
