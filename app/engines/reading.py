# one engine reading of a page range with the fields of config/engines.yaml, read through the stand's adapter
from functools import cache
from pathlib import Path

import settings
import yaml
from job_signals import Deferred

from engines import card, converter, converter_tools, docling_adapter, mineru_adapter, ocr_languages

ADAPTERS = {"docling": docling_adapter, "mineru": mineru_adapter}


@cache
def _conf() -> dict:
    return yaml.safe_load((settings.CONFIG_DIR / "engines.yaml").read_text())


# Docling's Tesseract gets every language of the book it has data for; MinerU reads the layer here, no OCR language
def fields(engine: str, regime: str, languages: list[str]) -> list[tuple[str, object]]:
    found = list(_conf()[engine][regime]["fields"].items())
    if engine != "docling":
        return found
    return found + [("ocr_lang", code) for code in ocr_languages.tesseract_codes(languages)]


def _out_of_memory(got: dict) -> bool:
    return "out of memory" in str(got.get("errors")).lower()


# a range the card has no memory for is read again in halves, down to the configured depth, and kept as its parts
def _readings(engine: str, path: Path, first: int, last: int, given: list[tuple[str, object]], ceiling: float,
              build: dict | None, splits: int | None, needed: str | None) -> list[dict]:
    splits = _conf()["out_of_memory_splits"] if splits is None else splits
    card.hand_to(engine)
    got = converter_tools.READ[engine](path, given, first, last, ceiling=ceiling, build=build)
    if got.get("status") in converter_tools.KEPT and (needed is None or got.get(needed)):
        return [got]
    if _out_of_memory(got) and splits > 0 and last > first:
        middle = (first + last) // 2
        return [r for a, b in ((first, middle), (middle + 1, last))
                for r in _readings(engine, path, a, b, given, ceiling, build, splits - 1, needed)]
    reason = "out of memory even in halves" if _out_of_memory(got) else got.get("status")
    raise RuntimeError(f"{engine} read pages {first}-{last} of {path.name} as {reason}: {got.get('errors')}")


def read(engine: str, path: Path, first: int, last: int, given: list[tuple[str, object]], ceiling: float,
         build: dict | None = None, splits: int | None = None) -> dict:
    got = _readings(engine, path, first, last, given, ceiling, build, splits, "structure")
    return got[0]["structure"] if len(got) == 1 else {"parts": [r["structure"] for r in got]}


# a kept reading may come without markdown; its halves are joined in page order
def read_markdown(engine: str, path: Path, first: int, last: int, given: list[tuple[str, object]], ceiling: float,
                  build: dict | None = None, splits: int | None = None) -> str:
    got = _readings(engine, path, first, last, given, ceiling, build, splits, None)
    return "\n".join(r.get("markdown") or "" for r in got)


def parts(structure: dict) -> list[dict]:
    return structure.get("parts", [structure])


# a converter that cannot say its build is asked again later rather than failing the job
def build(engine: str) -> dict:
    try:
        return converter.build(engine)
    except converter.WillNotStart as e:
        raise Deferred(f"{engine} cannot say its build: {e}", delay_seconds=300) from e


def adapt(engine: str, structure: dict, file_ord: int = 0, book_page=lambda page: page):
    adapted = [ADAPTERS[engine].read(p, file_ord, book_page) for p in parts(structure)]
    out = adapted[0]
    for part in adapted[1:]:
        out.blocks += part.blocks
        out.furniture += part.furniture
        out.furniture_at += part.furniture_at
        out.unknown += part.unknown
    return out


def languages() -> set[str]:
    return set(ocr_languages.listing()["installed"])
