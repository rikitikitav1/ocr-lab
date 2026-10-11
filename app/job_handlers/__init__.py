from collections.abc import Callable

from job_signals import Deferred, Final

__all__ = ["Deferred", "Final", "HANDLERS", "load_all", "register"]


HANDLERS: dict[str, Callable[[dict], dict | None]] = {}
# called once a job has ended for good, done or failed, never on a retry or a deferral
ENDED: dict[str, Callable[[dict, str, str | None], None]] = {}


def register(type: str, ended: Callable[[dict, str, str | None], None] | None = None):
    def wrap(fn):
        HANDLERS[type] = fn
        if ended is not None:
            ENDED[type] = ended
        return fn

    return wrap


def load_all() -> None:
    from job_handlers import book, builtin, evaluation, run, workbench  # noqa: F401
