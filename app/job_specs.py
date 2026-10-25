from functools import cache
from typing import Literal

import settings
import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class Refused(ValueError):
    pass


# refused because something still runs: wait for it rather than change the input
class Busy(Refused):
    def __init__(self, run_id: int):
        super().__init__(f"run {run_id} is still running; wait with wait_runs([{run_id}]) or cancel it first")
        self.run_id = run_id


# a book's chain opens with metadata when it is asked for, else with the page layout, which chains the rest
def chain_head(what: list[str]) -> str:
    return "metadata" if "metadata" in what else "layout_page"


class _Spec(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BookOptions(_Spec):
    book_id: int


# what intake chains after itself: metadata then structure as on submission, or structure alone when metadata waits
class IntakeOptions(BookOptions):
    then: list[Literal["metadata", "structure", "layout", "run"]] = ["metadata", "structure"]
    # a recollection collects every stage it chains again, a submission only what is stale
    force: bool = False

    @model_validator(mode="after")
    def _run_after_structure(self):
        if "run" in self.then and "structure" not in self.then:
            raise ValueError("run starts once the structure is collected; add structure to then")
        return self


# the book-level stages a recollection can ask for, and the ones that exist so far; one place for both doors
BOOK_STAGES = ("intake", "metadata", "structure", "layout")
BUILT_BOOK_STAGES = ("intake", "metadata", "structure", "layout")
RECOLLECT_DEFAULT = ["metadata"]


class RecollectOptions(BookOptions):
    what: list[Literal["intake", "metadata", "structure", "layout"]] = RECOLLECT_DEFAULT
    force: bool = False
    # a submission asking for a run starts one once the structure is collected
    run: bool = False


# the heading layout is read for one book from its current structure and page layout
class LayoutOptions(BookOptions):
    force: bool = False


# the structure's gold sets that are built; every door and the evaluation read this one list
STRUCTURE_SETS = ("bookmarks_off", "contents_off", "hips")


class StructureEvalOptions(_Spec):
    set: Literal[STRUCTURE_SETS]
    book_ids: list[int] | None = None


# the engines over rag-lab's converter_gold sections; `ids` narrows it to some sections
class ElementEvalOptions(_Spec):
    engines: list[Literal[(*settings.ENGINES, "assembled")]] = [*settings.ENGINES, "assembled"]
    ids: list[str] | None = None
    # run knob values the assembled reading is made with, as a profile would set them ("assembly.code_union": true)
    knobs: dict = {}


class RunOptions(_Spec):
    run_id: int


# a piece's jobs carry the round they belong to: 0 for the run, one more for each rerun or resume
class PieceOptions(RunOptions):
    ord: int
    round: int = 0


class ReadPieceOptions(RunOptions):
    ord: int
    round: int = 0
    engine: Literal[settings.ENGINES]


# one engine over a book's page range, outside any run; the reading is kept as a run's would be
class ReadRangeOptions(BookOptions):
    engine: Literal[settings.ENGINES]
    first_page: int
    last_page: int
    # every page read as a picture, the way a scan is, whatever text layer it has
    force_raster_only: bool = False

    @model_validator(mode="after")
    def _raster_is_mineru(self):
        if self.force_raster_only and self.engine != "mineru":
            raise ValueError("a raster reading is MinerU's; Docling reads a raster only inside a run")
        return self


# the deepest tree level a book is read at; deeper nodes ride inside their parent's piece
MAX_READING_LEVEL = 9


# a finished run's pieces assembled again from their kept readings with run knobs set over the profile's
class ReassembleOptions(RunOptions):
    knobs: dict
    ords: list[int] | None = None
    # cut the run at this tree level instead of its own; the re-read off cuts as runs read before it were cut
    reading_level: int | None = Field(None, ge=0, le=MAX_READING_LEVEL)
    reread: bool = True
    # the book-level lists made anew instead of read back, their hashes in the result, for a gate
    fresh: bool = False


class CleanupOptions(_Spec):
    dry_run: bool = True


class EmptyOptions(_Spec):
    pass


class PreviewOptions(_Spec):
    book_ids: list[int]
    knobs: dict = {}


# the parent a bulk door hangs its jobs under, so one wait covers them all
class BatchOptions(_Spec):
    door: str
    books: int = 0


# the lane is a property of the type, so a GPU job never lands where two could run at once
SPECS: dict[str, tuple[type[_Spec], str]] = {
    "intake": (IntakeOptions, "cpu"),
    # metadata reads what it can on the CPU and hands the rest to the card only when a step needs it
    "metadata": (RecollectOptions, "cpu"),
    "metadata_gpu": (RecollectOptions, "gpu"),
    "structure": (RecollectOptions, "cpu"),
    # a scan's contents are recognised on the GPU, so its structure runs there
    "structure_scan": (RecollectOptions, "gpu"),
    # the page layout comes before the structure and the heading layout after it, both from the text layer
    "layout_page": (RecollectOptions, "cpu"),
    "layout_headings": (LayoutOptions, "cpu"),
    "book_run": (RunOptions, "cpu"),
    "profile_search": (RunOptions, "gpu"),
    # a piece's readings take the card, engine by engine; its assembly reads them back on the CPU
    "read_piece": (ReadPieceOptions, "gpu"),
    "assemble_piece": (PieceOptions, "cpu"),
    "book_metrics": (RunOptions, "cpu"),
    "read_range": (ReadRangeOptions, "gpu"),
    "reassemble": (ReassembleOptions, "cpu"),
    "eval_run": (EmptyOptions, "cpu"),
    "structure_eval": (StructureEvalOptions, "cpu"),
    # the engines read on the card, so the measurement runs on the GPU lane
    "element_eval": (ElementEvalOptions, "gpu"),
    "cleanup": (CleanupOptions, "cpu"),
    "structure_preview": (PreviewOptions, "cpu"),
    "batch": (BatchOptions, "cpu"),
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
    # a job type without a budget would fall silently to the floor
    if missing := sorted(set(SPECS) - set(loaded)):
        raise ValueError(f"budgets.yaml: no attempts for {missing}")
    return loaded


def attempts_for(type: str) -> int:
    return budgets().get(type, BUDGET_MIN)


# what a caller filters jobs by and what each type takes; built names the types the worker has a handler for
def catalogue(built: set[str]) -> list[dict]:
    return [{"type": type, "lane": lane, "built": type in built, "attempts": attempts_for(type),
             "options": spec.model_json_schema()} for type, (spec, lane) in SPECS.items()]
