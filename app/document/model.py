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


class Heading(Placed):
    type: Literal["heading"] = "heading"
    text: str
    # 1 is right below the chapter's own heading; the chapter's place in the book is added by the writer
    level: int = Field(ge=1, le=5)
    level_source: str


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


class Caption(Placed):
    type: Literal["caption"] = "caption"
    text: str


class Note(Placed):
    type: Literal["note"] = "note"
    # the label as the book prints it ("Note", "Tip", "Совет"); the stand does not translate it
    label: str
    text: str


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


Block = Annotated[Heading | Paragraph | Code | Table | ListBlock | Figure | Caption | Note | Footnote | Formula
                  | PageMarker, Field(discriminator="type")]


class Chapter(BaseModel):
    ord: int
    title: str
    # the toc level: 1 for a part or a chapter at the top, 2 for a chapter inside a part
    level: int = Field(ge=1, le=5)
    first_page: int
    last_page: int
    # "service" for the unnumbered chapters before the first numbered one and after the last, so a reader can skip them
    role: Literal["service", "body"] = "body"
    blocks: list[Block] = []


class Document(BaseModel):
    title: str
    chapters: list[Chapter] = []


ListItem.model_rebuild()
