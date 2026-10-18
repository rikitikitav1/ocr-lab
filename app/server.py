import logging_setup
import settings
from api.v1 import books, eval, jobs, knobs, layout, runs, stand, structure, workbench
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from knobs import registry
from mcp_tools import KINDS, kind_of, mcp

logging_setup.configure(settings.LOG_LEVEL)
registry.validate()

mcp_app = mcp.http_app(path="/", stateless_http=True)
app = FastAPI(title="ocr-lab", lifespan=mcp_app.lifespan)
app.mount("/mcp", mcp_app)

for module in (books, eval, jobs, knobs, layout, runs, stand, structure, workbench):
    app.include_router(module.router, prefix="/v1")


# the same kinds an MCP caller reads at the head of a tool error
async def _typed(request, error: Exception):
    kind, status = kind_of(error)
    return JSONResponse(status_code=status, content={"error": {"kind": kind, "message": str(error)}})


# a body or query the route's model refuses is the caller's input to fix, told in the same shape as any refusal
async def _invalid(request, error: RequestValidationError):
    problems = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in error.errors())
    return JSONResponse(status_code=422, content={"error": {"kind": "refused", "message": problems}})


for cls, _, _ in KINDS:
    app.add_exception_handler(cls, _typed)
app.add_exception_handler(RequestValidationError, _invalid)
app.add_exception_handler(Exception, _typed)
