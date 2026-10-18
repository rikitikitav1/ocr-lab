# one book page of a run: which pieces hold it, how its boundary was cut, and what was written from it
import json
from collections import Counter

import artifacts
import settings
import text_layer
from assembly import referee
from document.model import PageMarker
from document.model import Piece as Model
from mcp_tools import tool
from orm.catalogue import Artifact, Run
from orm.db import Session
from sqlalchemy import select
from stages import intake
from stages import run_pieces as units_of_run

TEXT_CHARS = 120


def _kept(session, run_id: int, ord: int, name: str):
    row = session.scalar(select(Artifact).where(Artifact.run_id == run_id, Artifact.piece_ord == ord,
                                                Artifact.stage == "assemble", Artifact.name == name,
                                                Artifact.removed_at.is_(None)).order_by(Artifact.id.desc()).limit(1))
    return json.loads(artifacts.read(row)) if row is not None else None


def _layer(book_id: int, page: int) -> str:
    f = intake.file_of(intake.files_of(book_id), page)
    if f is None:
        return ""
    index = page - f.first_page
    return text_layer.page_texts(settings.DATA_DIR / f.file_path, [index]).get(index, "")


def _on(model: Model, page: int) -> list:
    out, here = [], False
    for block in model.blocks:
        if isinstance(block, PageMarker):
            here = block.book_page == page
        elif here:
            out.append(block)
    return out


def _row(block) -> dict:
    where, text = getattr(block, "where", None), referee.block_text(block)
    return {"type": block.type, "engine": where.engine if where else None, "box": where.box if where else None,
            "level": getattr(block, "level", None), "node": getattr(block, "node", None), "words": len(text.split()),
            "text": text[:TEXT_CHARS]}


def _words(text: str) -> Counter:
    return Counter(referee.WORD.findall(text.lower()))


@tool("page", "GET /v1/runs/{id}/pages/{page}",
      "One book page of a run: the pieces holding it, each piece's boundary records for that page (title found, "
      "tail blocks, what was dropped), its blocks on the page with type, engine, box, level and a text head, and the "
      "layer's words on the page against the words written from it (lost and extra).")
def page(id: int, page: int) -> dict:
    with Session() as session:
        run = session.get(Run, id)
        if run is None:
            raise LookupError(f"no run {id}")
        holding = [p for p in units_of_run.pieces(session, run) if p["first_page"] <= page <= p["last_page"]]
        if not holding:
            raise LookupError(f"no piece of run {id} holds page {page}")
        found = [(p, _kept(session, id, p["ord"], "model.json"), _kept(session, id, p["ord"], "boundaries.json"))
                 for p in holding]
        book_id = run.book_id
    pieces, written = [], Counter()
    for p, model, cuts in found:
        blocks = _on(Model.model_validate(model), page) if model else []
        written += sum((_words(referee.block_text(b)) for b in blocks), Counter())
        pieces.append({"ord": p["ord"], "title": p["title"], "first_page": p["first_page"],
                       "last_page": p["last_page"], "assembled": model is not None,
                       "boundaries": [r for r in cuts or [] if r.get("page") == page],
                       "blocks": [_row(b) for b in blocks]})
    layer = _words(_layer(book_id, page))
    return {"run": id, "page": page, "pieces": pieces, "layer_words": sum(layer.values()),
            "written_words": sum(written.values()), "lost": sum((layer - written).values()),
            "extra": sum((written - layer).values())}
