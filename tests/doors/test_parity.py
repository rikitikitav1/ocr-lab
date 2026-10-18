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


def test_every_tool_tells_a_client_what_it_does():
    import asyncio

    from mcp_tools import mcp

    listed = asyncio.run(mcp.list_tools())
    assert {t.name for t in listed} == set(TOOLS)
    assert [t.name for t in listed if len(t.description or "") < 30] == []


def test_a_wait_over_mcp_answers_before_the_client_s_idle_limit(monkeypatch):
    import asyncio

    from mcp_tools import MCP_WAIT_SECONDS, mcp
    from use_cases import runs

    seen = {}
    monkeypatch.setattr(runs, "_settled_runs", lambda ids, until: None)
    monkeypatch.setattr(runs.job_queue, "listen", lambda check, timeout: seen.update(timeout=timeout))
    monkeypatch.setattr(runs, "Session", None)
    # the call fails past the wait for want of a database; only the timeout it waited with matters here
    try:
        asyncio.run(mcp.call_tool("wait_runs", {"ids": [1], "timeout": 900}))
    except Exception:
        pass
    assert seen["timeout"] == MCP_WAIT_SECONDS
    listed = {t.name: t for t in asyncio.run(mcp.list_tools())}
    assert f"within {MCP_WAIT_SECONDS} s" in listed["wait_runs"].description
    assert "within" not in listed["queue"].description
