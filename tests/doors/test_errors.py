import asyncio

import net
import pytest
from engines import ocr_languages
from fastapi.testclient import TestClient
from fastmcp.exceptions import ToolError
from mcp_tools import mcp
from server import app


def _failing(error: Exception):
    def install(language):
        raise error

    return install


CASES = [
    (LookupError("no such language"), "missing", 404),
    (net.SourceDown("github.com", "timeouts"), "retry_later", 503),
    (RuntimeError("disk full"), "fault", 500),
]


@pytest.mark.parametrize("error, kind, status", CASES)
def test_a_failure_carries_its_kind_over_both_doors(monkeypatch, error, kind, status):
    monkeypatch.setattr(ocr_languages, "install", _failing(error))
    with pytest.raises(ToolError, match=f"^{kind}: "):
        asyncio.run(mcp.call_tool("install_ocr_language", {"language": "en"}))
    answer = TestClient(app, raise_server_exceptions=False).post("/v1/engines/ocr_languages",
                                                                 json={"language": "en"})
    assert answer.status_code == status
    assert answer.json()["error"]["kind"] == kind


def test_a_refusal_says_refused_over_both_doors():
    with pytest.raises(ToolError, match="^refused: "):
        asyncio.run(mcp.call_tool("structure_eval", {"set": "nonsense"}))
    answer = TestClient(app).post("/v1/eval/structure", json={"set": "nonsense"})
    assert answer.status_code == 400
    assert answer.json()["error"]["kind"] == "refused"
