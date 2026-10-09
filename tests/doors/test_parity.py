from mcp_tools import TOOLS
from server import app


def _routes() -> set[str]:
    return {f"{method.upper()} {path}" for path, ops in app.openapi()["paths"].items() for method in ops}


# an MCP client cannot send file bytes; it submits by path through add_book
REST_ONLY = {"POST /v1/books/upload"}


def test_every_route_has_a_tool_and_every_tool_a_route():
    tools = set(TOOLS.values())
    assert _routes() - tools - REST_ONLY == set(), "routes without an MCP tool"
    assert tools - _routes() == set(), "MCP tools without a route"
