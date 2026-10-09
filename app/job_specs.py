from functools import cache
from typing import Literal

import settings
import yaml
from pydantic import BaseModel, ConfigDict, ValidationError


class Refused(ValueError):
    pass


class _Spec(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BookOptions(_Spec):
    book_id: int


# the book-level stages a recollection can ask for, and the ones that exist so far; one place for both doors
BOOK_STAGES = ("intake", "metadata", "toc")
BUILT_BOOK_STAGES = ("intake", "metadata")
RECOLLECT_DEFAULT = ["metadata"]


class RecollectOptions(BookOptions):
    what: list[Literal["intake", "metadata", "toc"]] = RECOLLECT_DEFAULT
    force: bool = False


class RunOptions(_Spec):
    run_id: int


class ChapterOptions(RunOptions):
    ord: int


class CleanupOptions(_Spec):
    dry_run: bool = True


class EmptyOptions(_Spec):
    pass


# the lane is a property of the type, so a GPU job never lands where two could run at once
SPECS: dict[str, tuple[type[_Spec], str]] = {
    "intake": (BookOptions, "cpu"),
    "metadata": (RecollectOptions, "gpu"),
    "toc": (RecollectOptions, "cpu"),
    "book_run": (RunOptions, "cpu"),
    "profile_search": (RunOptions, "gpu"),
    "assemble_chapter": (ChapterOptions, "gpu"),
    "book_metrics": (RunOptions, "cpu"),
    "eval_run": (EmptyOptions, "cpu"),
    "cleanup": (CleanupOptions, "cpu"),
    "noop": (EmptyOptions, "cpu"),
    "noop_gpu": (EmptyOptions, "gpu"),
}

BUDGET_MIN, BUDGET_MAX = 3, 5


def lane(type: str) -> str:
    if type not in SPECS:
        raise Refused(f"unknown job type {type!r}")
    return SPECS[type][1]


def check(type: str, options: dict | None) -> dict:
    spec, _ = SPECS.get(type, (None, None))
    if spec is None:
        raise Refused(f"unknown job type {type!r}")
    try:
        return spec.model_validate(options or {}).model_dump()
    except ValidationError as bad:
        raise Refused(f"{type}: {bad.errors(include_url=False)}") from bad


@cache
def budgets() -> dict[str, int]:
    loaded = yaml.safe_load((settings.CONFIG_DIR / "budgets.yaml").read_text())["attempts"]
    wrong = {k: v for k, v in loaded.items() if not BUDGET_MIN <= v <= BUDGET_MAX}
    if wrong:
        raise ValueError(f"budgets.yaml: attempts must be {BUDGET_MIN} to {BUDGET_MAX}, got {wrong}")
    return loaded


def attempts_for(type: str) -> int:
    return budgets().get(type, BUDGET_MIN)
