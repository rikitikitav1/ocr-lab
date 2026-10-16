from fastapi import APIRouter
from pydantic import BaseModel
from use_cases import evaluation

router = APIRouter()


class StructureEval(BaseModel):
    set: str
    book_ids: list[int] | None = None


class ElementEval(BaseModel):
    engines: list[str] | None = None
    ids: list[str] | None = None
    knobs: dict | None = None


@router.post("/eval/elements", status_code=202)
def element_eval(body: ElementEval):
    return evaluation.element_eval(body.engines, body.ids, body.knobs)


@router.post("/eval/structure", status_code=202)
def structure_eval(body: StructureEval):
    return evaluation.structure_eval(body.set, body.book_ids)


@router.get("/eval/structure/compare")
def structure_eval_compare(job_a: int, job_b: int):
    return evaluation.structure_eval_compare(job_a, job_b)
