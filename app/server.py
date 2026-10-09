import job_specs
import logging_setup
import settings
from api.v1 import books, jobs, stand
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from mcp_tools import mcp

logging_setup.configure(settings.LOG_LEVEL)

mcp_app = mcp.http_app(path="/", stateless_http=True)
app = FastAPI(title="ocr-lab", lifespan=mcp_app.lifespan)
app.mount("/mcp", mcp_app)

for module in (books, jobs, stand):
    app.include_router(module.router, prefix="/v1")


@app.exception_handler(job_specs.Refused)
async def _refused(request, bad: job_specs.Refused):
    return JSONResponse(status_code=400, content={"error": {"kind": "refused", "message": str(bad)}})


@app.exception_handler(LookupError)
async def _missing(request, bad: LookupError):
    return JSONResponse(status_code=404, content={"error": {"kind": "missing", "message": str(bad)}})
