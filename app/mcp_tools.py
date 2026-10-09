# one MCP tool per use case; the REST route calls the same function
from collections.abc import Callable

from fastmcp import FastMCP

mcp = FastMCP("ocr-lab")
TOOLS: dict[str, str] = {}


def tool(name: str, route: str) -> Callable:
    def wrap(fn):
        TOOLS[name] = route
        mcp.tool(name=name)(fn)
        return fn

    return wrap
