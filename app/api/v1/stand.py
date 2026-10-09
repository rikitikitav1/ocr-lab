from fastapi import APIRouter
from use_cases import stand

router = APIRouter()


@router.get("/stand")
def get_stand():
    return stand.stand()
