# one GPU for every engine: a handover releases the others before the target takes it
import time

import httpx
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


def _ollama_loaded() -> list[str]:
    try:
        seen = net.get(settings.OLLAMA_BASE_URL + "/api/ps", timeout=5)
        seen.raise_for_status()
        return [m["name"] for m in seen.json().get("models", [])]
    except httpx.HTTPError:
        return []


def _ollama_unload(model: str) -> None:
    net.post(settings.OLLAMA_BASE_URL + "/api/generate", json={"model": model, "keep_alive": 0}, timeout=60)


# read from the servers each time: a table of holders would drift from them
def holders() -> list[str]:
    held = [name for name in settings.CONVERTERS if converter.reading(name)[0] == converter.HOLDS]
    if _ollama_loaded():
        held.append(OLLAMA)
    return held


def hand_to(target: str) -> None:
    try:
        _hand_to(target)
    except net.SourceDown as e:
        raise CardNotHanded(f"{target}: {e}") from e


def _hand_to(target: str) -> None:
    for name in holders():
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
    log.info("card.handed", engine=target)


def _until(done, why: str) -> None:
    deadline = time.monotonic() + WAIT_CEILING
    while time.monotonic() < deadline:
        if done():
            return
        time.sleep(POLL_SECONDS)
    raise CardNotHanded(f"{why} in {WAIT_CEILING}s")
