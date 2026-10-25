# Docling's json_content read into the stand's blocks in body order; running heads are counted, not kept
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field

from document.model import (
    Block,
    Caption,
    Cell,
    Code,
    Figure,
    Formula,
    Heading,
    ListBlock,
    ListItem,
    PageMarker,
    Paragraph,
    Table,
    Where,
)
from elements import footnotes

PROSE = {"text", "paragraph", "reference", "checkbox_selected", "checkbox_unselected", "handwritten_text"}
HEADINGS = {"section_header", "title"}
FURNITURE = {"page_header", "page_footer"}
LISTS = {"list", "ordered_list"}
MARKER_NUMBER = re.compile(r"(\d+)")


@dataclass
class Read:
    blocks: list[Block] = field(default_factory=list)
    furniture: list[str] = field(default_factory=list)
    # the same, with the file page and the engine's type, for the readers that decide by the page layout
    furniture_at: list[tuple[int, str, str]] = field(default_factory=list)
    # labels the adapter has no block for; their text is kept as prose so nothing is lost
    unknown: Counter = field(default_factory=Counter)


class _Walk:
    def __init__(self, doc: dict, file_ord: int, book_page: Callable[[int], int],
                 keep_image: Callable[[dict], str]):
        self.doc, self.file_ord, self.book_page, self.keep_image = doc, file_ord, book_page, keep_image
        self.out = Read()
        self.page: int | None = None
        self.notes = footnotes.Notes()

    # Docling's boxes are points from the bottom left; the model keeps shares of the page from the top left
    def where(self, item: dict) -> Where | None:
        provs = item.get("prov") or []
        if not provs or "bbox" not in provs[0]:
            return None
        bbox, page = provs[0]["bbox"], provs[0]["page_no"]
        size = (self.doc.get("pages") or {}).get(str(page), {}).get("size") or {}
        width, height = size.get("width"), size.get("height")
        if not width or not height:
            return None
        top, bottom = bbox["t"], bbox["b"]
        if bbox.get("coord_origin", "BOTTOMLEFT") == "BOTTOMLEFT":
            top, bottom = height - top, height - bottom
        return Where(page=page, box=(bbox["l"] / width, top / height, bbox["r"] / width, bottom / height),
                     engine="docling")

    def put(self, block, item: dict) -> None:
        block.where = self.where(item)
        self.out.blocks.append(block)

    def item(self, ref: str) -> dict:
        _, kind, index = ref.split("/")
        return self.doc[kind][int(index)]

    def at(self, item: dict) -> None:
        provs = item.get("prov") or []
        if provs and provs[0]["page_no"] != self.page:
            self.page = provs[0]["page_no"]
            self.out.blocks.append(PageMarker(book_page=self.book_page(self.page), file_ord=self.file_ord,
                                              file_page=self.page))

    def walk(self, ref: str) -> None:
        item = self.item(ref)
        if item.get("content_layer") == "furniture" or item.get("label") in FURNITURE:
            self.out.furniture.append(item.get("text", ""))
            provs = item.get("prov") or []
            self.out.furniture_at.append((provs[0]["page_no"] if provs else self.page, item.get("label", ""),
                                          item.get("text", "")))
            return
        kind = ref.split("/")[1]
        if kind == "groups":
            self.group(item)
        elif kind == "tables":
            self.table(item)
        elif kind == "pictures":
            self.picture(item)
        else:
            self.text(item)

    def group(self, item: dict) -> None:
        if item["label"] in LISTS:
            if listed := self.list_block(item):
                first = next((self.item(c["$ref"]) for c in item["children"] if c["$ref"].startswith("#/texts/")),
                             item)
                self.put(listed, first)
            return
        if item["label"] == "inline":
            texts = [self.item(c["$ref"]) for c in item["children"]]
            if texts:
                self.at(texts[0])
                self.put(Paragraph(text=" ".join(t.get("text", "") for t in texts)), texts[0])
            return
        for child in item["children"]:
            self.walk(child["$ref"])

    def list_block(self, group: dict) -> ListBlock | None:
        items, ordered, start = [], group["label"] == "ordered_list", 1
        for child in group["children"]:
            entry = self.item(child["$ref"])
            if child["$ref"].startswith("#/groups/"):
                if items and (nested := self.list_block(entry)):
                    items[-1].children.append(nested)
                continue
            self.at(entry)
            if not items:
                ordered = ordered or bool(entry.get("enumerated"))
                if ordered and (m := MARKER_NUMBER.search(entry.get("marker") or "")):
                    start = int(m.group(1))
            item = ListItem(text=entry.get("text", ""))
            for sub in entry.get("children", []):
                if sub["$ref"].startswith("#/groups/") and (nested := self.list_block(self.item(sub["$ref"]))):
                    item.children.append(nested)
            items.append(item)
        return ListBlock(ordered=ordered, start=start, items=items) if items else None

    def text(self, item: dict) -> None:
        label, text = item["label"], item.get("text", "")
        self.at(item)
        if label in HEADINGS:
            block = Heading(text=text, level=min(max(item.get("level", 1), 1), 5), level_source="docling")
        elif label == "code":
            language = item.get("code_language")
            block = Code(text=text, language=None if language in (None, "unknown") else language.lower())
        elif label == "formula":
            block = Formula(latex=text or item.get("orig", ""))
        elif label == "footnote":
            block = self.notes.read(text)
        elif label == "caption":
            block = Caption(text=text)
        else:
            if label not in PROSE:
                self.out.unknown[label] += 1
            block = Paragraph(text=text)
        self.put(block, item)

    def captions(self, item: dict) -> None:
        for ref in item.get("captions", []):
            caption = self.item(ref["$ref"])
            self.put(Caption(text=caption.get("text", "")), caption)

    def table(self, item: dict) -> None:
        self.at(item)
        self.put(Table(rows=grid(item["data"])), item)
        self.captions(item)
        for ref in item.get("footnotes", []):
            note = self.item(ref["$ref"])
            self.put(self.notes.read(note.get("text", "")), note)

    def picture(self, item: dict) -> None:
        self.at(item)
        self.put(Figure(image=self.keep_image(item)), item)
        self.captions(item)


# Docling leaves empty cells out of `table_cells`, so each cell goes to its own column and the gaps are empty cells
def grid(data: dict) -> list[list[Cell]]:
    cells = data.get("table_cells") or []
    if not cells:
        return []
    starts = {(c["start_row_offset_idx"], c["start_col_offset_idx"]): c for c in cells}
    def ends(c: dict, axis: str, span: str) -> range:
        start = c[f"start_{axis}_offset_idx"]
        return range(start, max(c.get(f"end_{axis}_offset_idx", start + max(c.get(span, 1), 1)), start + 1))

    covered = {(r, k) for c in cells for r in ends(c, "row", "row_span") for k in ends(c, "col", "col_span")}
    rows = max(data.get("num_rows") or 0, max(r for r, _ in covered) + 1)
    cols = max(data.get("num_cols") or 0, max(k for _, k in covered) + 1)
    out = []
    for r in range(rows):
        row = []
        for k in range(cols):
            if (c := starts.get((r, k))) is not None:
                row.append(Cell(text=c["text"], header=bool(c.get("column_header")),
                                rowspan=max(c.get("row_span", 1), 1), colspan=max(c.get("col_span", 1), 1)))
            elif (r, k) not in covered:
                row.append(Cell(text=""))
        out.append(row)
    return [row for row in out if row]


def read(doc: dict, file_ord: int, book_page: Callable[[int], int],
         keep_image: Callable[[dict], str] = lambda picture: picture["self_ref"]) -> Read:
    walk = _Walk(doc, file_ord, book_page, keep_image)
    for child in doc["body"]["children"]:
        walk.walk(child["$ref"])
    return walk.out
