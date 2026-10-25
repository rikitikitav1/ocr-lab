# the stand's own document: engines are read into it, rules change it, writers read only it
from typing import Annotated, Literal

from pydantic import BaseModel, Field


# where an engine put a block: the page in its file, the box as shares of the page from the top left, the engine
class Where(BaseModel):
    page: int
    box: tuple[float, float, float, float]
    engine: str


class Placed(BaseModel):
    where: Where | None = None
    # the structure node the block belongs to; by_page when its node was set by the page, no title being found
    parent_ord: int | None = None
    by_page: bool = False
    # a running head or folio the page layout claims (folio, repeat, side); dropped once the nodes are pinned
    slot: str | None = None


class Heading(Placed):
    type: Literal["heading"] = "heading"
    text: str
    # 1 is right below the piece's own heading; the piece's place in the book is added by the writer
    level: int = Field(ge=1, le=5)
    level_source: str
    # the structure node this heading opens, when one is pinned to it
    node: int | None = None


class Paragraph(Placed):
    type: Literal["paragraph"] = "paragraph"
    text: str


class Code(Placed):
    type: Literal["code"] = "code"
    text: str
    language: str | None = None


class Cell(BaseModel):
    text: str
    header: bool = False
    rowspan: int = Field(default=1, ge=1)
    colspan: int = Field(default=1, ge=1)


class Table(Placed):
    type: Literal["table"] = "table"
    rows: list[list[Cell]]


class ListItem(BaseModel):
    text: str
    slot: str | None = None
    children: list["ListBlock"] = []


class ListBlock(Placed):
    type: Literal["list"] = "list"
    ordered: bool
    start: int = 1
    items: list[ListItem]


class Figure(Placed):
    type: Literal["figure"] = "figure"
    image: str
    alt: str = ""
    # a copy of the Caption block beside the picture, for a reader that takes the figure out of its page
    caption: str | None = None


class Caption(Placed):
    type: Literal["caption"] = "caption"
    text: str


class Note(Placed):
    type: Literal["note"] = "note"
    # the label as the book prints it ("Note", "Tip", "Совет"); the stand does not translate it
    label: str
    text: str


# a chapter's own list of its sections on its opening page, kept apart so a reader can leave it out
class Contents(Placed):
    type: Literal["contents"] = "contents"
    entries: list[str]


class Footnote(Placed):
    type: Literal["footnote"] = "footnote"
    mark: str
    text: str


class Formula(Placed):
    type: Literal["formula"] = "formula"
    latex: str


class PageMarker(BaseModel):
    type: Literal["page"] = "page"
    book_page: int
    file_ord: int
    file_page: int


Block = Annotated[Heading | Paragraph | Code | Table | ListBlock | Figure | Caption | Note | Contents | Footnote
                  | Formula | PageMarker, Field(discriminator="type")]


# a node of the book's structure as a unit holds it: its level in the book, its parent and whether its heading was found
class Node(BaseModel):
    ord: int
    title: str
    level: int
    parent_ord: int | None = None
    first_page: int | None = None
    last_page: int | None = None
    pinned: bool = False
    # pinned and still a heading: a unit at the deepest level writes its headings as paragraphs, with no anchor
    anchored: bool = False


class Piece(BaseModel):
    ord: int
    title: str
    # the structure level: 1 for a top node, 2 for a node inside it
    level: int = Field(ge=1, le=5)
    first_page: int
    last_page: int
    # "service" for the unnumbered pieces before the first numbered one and after the last, so a reader can skip them
    role: Literal["service", "body"] = "body"
    blocks: list[Block] = []
    # the unit's own node first, then the nodes inside it in order
    nodes: list[Node] = []


class Document(BaseModel):
    title: str
    pieces: list[Piece] = []


ListItem.model_rebuild()
