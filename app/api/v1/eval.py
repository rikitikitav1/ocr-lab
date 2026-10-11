from fastapi import APIRouter
from pydantic import BaseModel
from use_cases import evaluation

router = APIRouter()


class TocEval(BaseModel):
    set: str
    book_ids: list[int] | None = None


class ElementEval(BaseModel):
    engines: list[str] | None = None
    ids: list[str] | None = None
    knobs: dict | None = None


@router.post("/eval/elements", status_code=202)
def element_eval(body: ElementEval):
    return evaluation.element_eval(body.engines, body.ids, body.knobs)


@router.post("/eval/toc", status_code=202)
def toc_eval(body: TocEval):
    return evaluation.toc_eval(body.set, body.book_ids)


@router.get("/eval/toc/compare")
def toc_eval_compare(job_a: int, job_b: int):
    return evaluation.toc_eval_compare(job_a, job_b)
