# MinerU's docvortex.middle read into the stand's blocks page by page; running heads are counted, not kept
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from html.parser import HTMLParser

from document.model import (
    Block,
    Caption,
    Cell,
    Code,
    Figure,
    Footnote,
    Formula,
    Heading,
    ListBlock,
    ListItem,
    PageMarker,
    Paragraph,
    Table,
    Where,
)

FURNITURE = {"header", "footer", "page_number", "aside_text"}
HEADINGS = {"doc_title", "paragraph_title", "title"}
PROSE = {"text", "ref_text"}
FIGURES = {"image", "chart"}
CAPTIONS = {"image_caption", "chart_caption", "table_caption"}
NOTES = {"image_footnote", "chart_footnote", "table_footnote"}
FOOTNOTE_MARK = re.compile(r"^\s*(\d{1,3}|[*†‡§¶]{1,3})\s+(.+)$", re.S)


@dataclass
class Read:
    blocks: list[Block] = field(default_factory=list)
    furniture: list[str] = field(default_factory=list)
    # types the adapter has no block for; their text is kept as prose so nothing is lost
    unknown: Counter = field(default_factory=Counter)


def _spans(content) -> str:
    if isinstance(content, str):
        return content
    parts = []
    for span in content or []:
        text = _spans(span.get("content"))
        parts.append(f"${text}$" if span.get("type") == "equation_inline" else text)
    return "".join(parts)


class _Cells(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows: list[list[Cell]] = []
        self.cell: dict | None = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "tr":
            self.rows.append([])
        elif tag == "br" and self.cell is not None:
            self.cell["text"] += "\n"
        elif tag in ("td", "th") and self.rows:
            self.cell = {"text": "", "header": tag == "th", "rowspan": int(a.get("rowspan") or 1),
                         "colspan": int(a.get("colspan") or 1)}

    def handle_data(self, data):
        if self.cell is not None:
            self.cell["text"] += data

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None:
            self.rows[-1].append(Cell(**self.cell))
            self.cell = None


def table_rows(html: str) -> list[list[Cell]]:
    parser = _Cells()
    parser.feed(html)
    return [row for row in parser.rows if row]


class _Walk:
    def __init__(self, file_ord: int, book_page: Callable[[int], int], keep_image: Callable[[dict, int], str]):
        self.file_ord, self.book_page, self.keep_image = file_ord, book_page, keep_image
        self.out = Read()
        self.unmarked = 0

    def footnote(self, text: str) -> Footnote:
        if m := FOOTNOTE_MARK.match(text):
            return Footnote(mark=m.group(1), text=m.group(2).strip())
        # a note printed without a mark gets one that cannot clash with the book's own numbers
        self.unmarked += 1
        return Footnote(mark=f"note{self.unmarked}", text=text.strip())

    def last_paragraph(self) -> Paragraph | None:
        for block in reversed(self.out.blocks):
            if isinstance(block, Paragraph):
                return block
            if not isinstance(block, PageMarker):
                return None
        return None

    # MinerU's boxes are already shares of the page from the top left
    def place(self, start: int, source: dict, page: int) -> None:
        box = source.get("bbox")
        if not box or len(box) != 4:
            return
        for added in self.out.blocks[start:]:
            if not isinstance(added, PageMarker) and added.where is None:
                added.where = Where(page=page, box=tuple(box), engine="mineru")

    def parts(self, block: dict, page: int) -> None:
        for part in block.get("content") or []:
            start = len(self.out.blocks)
            self.part(block, part, page)
            self.place(start, part if part.get("bbox") else block, page)

    def part(self, block: dict, part: dict, page: int) -> None:
        kind, text = part.get("type"), _spans(part.get("content"))
        if kind in ("image_body", "chart_body"):
            self.out.blocks.append(Figure(image=self.keep_image(part, page)))
        elif kind == "table_body":
            self.out.blocks.append(Table(rows=table_rows(text)))
        elif kind == "code_body":
            language = block.get("guess_lang")
            self.out.blocks.append(Code(text=text, language=None if language in (None, "", "txt") else language))
        elif kind in CAPTIONS:
            self.out.blocks.append(Caption(text=text))
        elif kind in NOTES:
            self.out.blocks.append(self.footnote(text))
        else:
            self.out.unknown[f"{block['type']}>{kind}"] += 1
            self.out.blocks.append(Paragraph(text=text))

    def block(self, block: dict, page: int) -> None:
        start = len(self.out.blocks)
        self.kind(block, page)
        self.place(start, block, page)

    def kind(self, block: dict, page: int) -> None:
        kind = block["type"]
        if kind in FURNITURE:
            self.out.furniture.append(_spans(block.get("content")))
        elif kind in HEADINGS:
            self.out.blocks.append(Heading(text=_spans(block.get("content")),
                                           level=min(max(block.get("level") or 1, 1), 5), level_source="mineru"))
        elif kind in PROSE:
            text = _spans(block.get("content"))
            # a paragraph broken by the page goes on in the one before the page marker
            if block.get("continues_prev") and (before := self.last_paragraph()) is not None:
                before.text = f"{before.text} {text}"
            else:
                self.out.blocks.append(Paragraph(text=text))
        elif kind == "page_footnote":
            self.out.blocks.append(self.footnote(_spans(block.get("content"))))
        elif kind == "equation":
            self.out.blocks.append(Formula(latex=_spans(block.get("content"))))
        elif kind == "index":
            self.out.blocks.append(Paragraph(text="\n".join(_spans(line.get("content")).strip()
                                                            for line in block.get("content") or [])))
        # no reading so far has had a list, so this shape is a guess until one does
        elif kind == "list":
            items = [ListItem(text=_spans(item.get("content")).strip()) for item in block.get("content") or []]
            if items:
                self.out.blocks.append(ListBlock(ordered=False, items=items))
        elif kind in FIGURES or kind in ("table", "code"):
            self.parts(block, page)
        else:
            self.out.unknown[kind] += 1
            self.out.blocks.append(Paragraph(text=_spans(block.get("content"))))


# page_idx counts from the start of the file, so the file page is page_idx + 1 whatever range was read
def read(doc: dict, file_ord: int, book_page: Callable[[int], int],
         keep_image: Callable[[dict, int], str] = lambda part, page: f"page{page}.{part.get('index', 0)}") -> Read:
    walk = _Walk(file_ord, book_page, keep_image)
    for page in sorted(doc.get("pages", []), key=lambda p: p["page_idx"]):
        file_page = page["page_idx"] + 1
        walk.out.blocks.append(PageMarker(book_page=book_page(file_page), file_ord=file_ord, file_page=file_page))
        for block in sorted(page.get("blocks", []), key=lambda b: b.get("index", 0)):
            walk.block(block, file_page)
    return walk.out
