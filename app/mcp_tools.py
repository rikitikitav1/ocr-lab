# one MCP tool per use case; the REST route calls the same function
import functools
import inspect
from collections.abc import Callable

import job_specs
import logging_setup
import net
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

log = logging_setup.get_logger(__name__)
mcp = FastMCP("ocr-lab")
TOOLS: dict[str, str] = {}

# what a caller does next: fix the input, look elsewhere, or try again later; anything else is a fault
KINDS: tuple[tuple[type[Exception], str, int], ...] = (
    (job_specs.Busy, "busy", 409),
    (job_specs.Refused, "refused", 400),
    (LookupError, "missing", 404),
    (net.SourceDown, "retry_later", 503),
)


def kind_of(error: Exception) -> tuple[str, int]:
    for cls, kind, status in KINDS:
        if isinstance(error, cls):
            return kind, status
    return "fault", 500


# an MCP client gives up on a call silent for 300 s, so a wait over MCP answers before that and is called again
MCP_WAIT_SECONDS = 240


# the description is what an MCP client reads about the tool, since the house rules leave functions without docstrings
def tool(name: str, route: str, description: str) -> Callable:
    def wrap(fn):
        waits = inspect.signature(fn).parameters.get("timeout")
        told = "" if waits is None else f" Over MCP it answers within {MCP_WAIT_SECONDS} s; call again on a timeout."

        @functools.wraps(fn)
        def typed(*args, **kwargs):
            if waits is not None:
                kwargs["timeout"] = min(kwargs.get("timeout", waits.default), MCP_WAIT_SECONDS)
            try:
                return fn(*args, **kwargs)
            except Exception as error:
                kind, _ = kind_of(error)
                if kind == "fault":
                    log.exception("tool.fault", tool=name, error=str(error))
                raise ToolError(f"{kind}: {error}") from error

        TOOLS[name] = route
        mcp.tool(name=name, description=description + told)(typed)
        return fn

    return wrap
