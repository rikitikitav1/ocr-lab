# the supervisor in each converter image starts its tool only while it holds the card
import httpx
import logging_setup
import net
import settings

log = logging_setup.get_logger(__name__)

HTTP_TIMEOUT = 10
# the supervisor kills a stubborn tool after 20 s and waits 20 s more
LET_GO_TIMEOUT = 45
HOLDS, FREE, DOWN, UNKNOWN = "holds", "free", "down", "unknown"


class WillNotStart(RuntimeError):
    pass


def base_url(name: str) -> str:
    return settings.CONVERTERS[name]


def reading(name: str) -> tuple[str, dict]:
    try:
        seen = net.get(base_url(name) + "/supervisor", timeout=HTTP_TIMEOUT)
        seen.raise_for_status()
        body = seen.json()
        return body.get("state", UNKNOWN), body
    # net turns a dead or silent supervisor into SourceDown after its retries
    except net.SourceDown as e:
        if "Timeout" in e.reason:
            log.warning("converter.state_unknown", engine=name, error=e.reason)
            return UNKNOWN, {}
        return DOWN, {}
    except httpx.HTTPStatusError as e:
        log.warning("converter.state_unknown", engine=name, error=str(e))
        return UNKNOWN, {}


# the build stamp baked into the image; a reading without it cannot be reproduced
def build(name: str) -> dict:
    stamp = reading(name)[1].get("build")
    if not stamp:
        raise WillNotStart(f"{name}: the supervisor reports no build stamp")
    return stamp


def take_once(name: str) -> bool:
    seen = net.post(base_url(name) + "/supervisor/take", timeout=HTTP_TIMEOUT)
    seen.raise_for_status()
    body = seen.json()
    if body.get("permanent"):
        raise WillNotStart(f"{name}: {body.get('reason')}")
    return bool(body.get("ready"))


def let_go(name: str) -> None:
    seen = net.post(base_url(name) + "/supervisor/let_go", timeout=LET_GO_TIMEOUT)
    seen.raise_for_status()
    if seen.json().get("held"):
        log.warning("converter.still_held", engine=name, reason=seen.json().get("reason"))
