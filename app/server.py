import logging_setup
import settings
from api.v1 import books, eval, jobs, knobs, runs, stand, toc, workbench
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from mcp_tools import KINDS, kind_of, mcp

logging_setup.configure(settings.LOG_LEVEL)

mcp_app = mcp.http_app(path="/", stateless_http=True)
app = FastAPI(title="ocr-lab", lifespan=mcp_app.lifespan)
app.mount("/mcp", mcp_app)

for module in (books, eval, jobs, knobs, runs, stand, toc, workbench):
    app.include_router(module.router, prefix="/v1")


# the same kinds an MCP caller reads at the head of a tool error
async def _typed(request, error: Exception):
    kind, status = kind_of(error)
    return JSONResponse(status_code=status, content={"error": {"kind": kind, "message": str(error)}})


for cls, _, _ in KINDS:
    app.add_exception_handler(cls, _typed)
app.add_exception_handler(Exception, _typed)
