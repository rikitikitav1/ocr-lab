from collections.abc import Callable


# waiting for something outside the job; it does not spend an attempt
class Deferred(Exception):
    def __init__(self, message: str, delay_seconds: int = 60):
        super().__init__(message)
        self.delay_seconds = delay_seconds


# a failure retries cannot fix
class Final(Exception):
    pass


HANDLERS: dict[str, Callable[[dict], dict | None]] = {}


def register(type: str):
    def wrap(fn):
        HANDLERS[type] = fn
        return fn

    return wrap


def load_all() -> None:
    from job_handlers import book, builtin  # noqa: F401
