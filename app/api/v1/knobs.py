from fastapi import APIRouter
from pydantic import BaseModel
from use_cases import knobs

router = APIRouter()


@router.get("/knobs")
def get_knobs():
    return knobs.knobs()


@router.get("/presets")
def get_presets():
    return knobs.presets()


@router.get("/profiles/{id}")
def get_profile(id: int):
    return knobs.profile(id)


class Derive(BaseModel):
    set: dict = {}
    pieces: dict[str, dict] = {}


@router.post("/profiles/{id}/derive", status_code=201)
def derive_profile(id: int, body: Derive):
    return knobs.derive_profile(id, body.set, body.pieces)
