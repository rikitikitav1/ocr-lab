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


# what intake chains after itself: metadata then toc as on submission, or toc alone when metadata waits
class IntakeOptions(BookOptions):
    then: list[Literal["metadata", "toc", "run"]] = ["metadata", "toc"]
    # a recollection collects every stage it chains again, a submission only what is stale
    force: bool = False


# the book-level stages a recollection can ask for, and the ones that exist so far; one place for both doors
BOOK_STAGES = ("intake", "metadata", "toc")
BUILT_BOOK_STAGES = ("intake", "metadata", "toc")
RECOLLECT_DEFAULT = ["metadata"]


class RecollectOptions(BookOptions):
    what: list[Literal["intake", "metadata", "toc"]] = RECOLLECT_DEFAULT
    force: bool = False
    # a submission asking for a run starts one once the toc is collected
    run: bool = False


class TocEvalOptions(_Spec):
    set: Literal["bookmarks_off", "hips", "longdocbench"]
    book_ids: list[int] | None = None


# the engines over rag-lab's converter_gold sections; `ids` narrows it to some sections
class ElementEvalOptions(_Spec):
    engines: list[Literal[(*settings.ENGINES, "assembled")]] = [*settings.ENGINES, "assembled"]
    ids: list[str] | None = None
    # run knob values the assembled reading is made with, as a profile would set them ("assembly.code_union": true)
    knobs: dict = {}


class RunOptions(_Spec):
    run_id: int


# a chapter's jobs carry the round they belong to: 0 for the run, one more for each rerun or resume
class ChapterOptions(RunOptions):
    ord: int
    round: int = 0


class ReadChapterOptions(RunOptions):
    ord: int
    round: int = 0
    engine: Literal[settings.ENGINES]


# one engine over a book's page range, outside any run; the reading is kept as a run's would be
class ReadRangeOptions(BookOptions):
    engine: Literal[settings.ENGINES]
    first_page: int
    last_page: int


# a finished run's chapters assembled again from their kept readings with run knobs set over the profile's
class ReassembleOptions(RunOptions):
    knobs: dict
    ords: list[int] | None = None


class CleanupOptions(_Spec):
    dry_run: bool = True


class EmptyOptions(_Spec):
    pass


# the lane is a property of the type, so a GPU job never lands where two could run at once
SPECS: dict[str, tuple[type[_Spec], str]] = {
    "intake": (IntakeOptions, "cpu"),
    # metadata reads what it can on the CPU and hands the rest to the card only when a step needs it
    "metadata": (RecollectOptions, "cpu"),
    "metadata_gpu": (RecollectOptions, "gpu"),
    "toc": (RecollectOptions, "cpu"),
    # a scan's contents are recognised on the GPU, so its toc runs there
    "toc_scan": (RecollectOptions, "gpu"),
    "book_run": (RunOptions, "cpu"),
    "profile_search": (RunOptions, "gpu"),
    # a chapter's readings take the card, engine by engine; its assembly reads them back on the CPU
    "read_chapter": (ReadChapterOptions, "gpu"),
    "assemble_chapter": (ChapterOptions, "cpu"),
    "book_metrics": (RunOptions, "cpu"),
    "read_range": (ReadRangeOptions, "gpu"),
    "reassemble": (ReassembleOptions, "cpu"),
    "eval_run": (EmptyOptions, "cpu"),
    "toc_eval": (TocEvalOptions, "cpu"),
    # the engines read on the card, so the measurement runs on the GPU lane
    "element_eval": (ElementEvalOptions, "gpu"),
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


# what a caller filters jobs by and what each type takes; built names the types the worker has a handler for
def catalogue(built: set[str]) -> list[dict]:
    return [{"type": type, "lane": lane, "built": type in built, "attempts": attempts_for(type),
             "options": spec.model_json_schema()} for type, (spec, lane) in SPECS.items()]
