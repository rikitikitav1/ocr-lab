from fastapi import APIRouter
from pydantic import BaseModel
from use_cases import stand

router = APIRouter()


@router.get("/stand")
def get_stand():
    return stand.stand()


class OcrLanguage(BaseModel):
    language: str


@router.get("/engines/ocr_languages")
def ocr_languages():
    return stand.ocr_language_list()


@router.post("/engines/ocr_languages")
def install_ocr_language(body: OcrLanguage):
    return stand.install_ocr_language(body.language)
