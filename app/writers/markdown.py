# Markdown from the document model, by contracts/bundle.md; it reads nothing but the model
import re
from html import escape

from document.model import (
    Caption,
    Chapter,
    Code,
    Document,
    Figure,
    Footnote,
    Formula,
    Heading,
    ListBlock,
    Note,
    PageMarker,
    Paragraph,
    Table,
)

MAX_LEVEL = 6
# a line of text starting like Markdown syntax would turn into a heading, a list or a quote
LEADING_SYNTAX = re.compile(r"^(\s*)(#{1,6}\s|>|[-*+]\s|\d+[.)]\s|={3,}|-{3,}|\|)")


class LevelTooDeep(ValueError):
    pass


# a backslash works only before punctuation, so "1. x" becomes "1\. x" and "# x" becomes "\# x"
def _escaped(m: re.Match) -> str:
    syntax = m.group(2)
    at = next(i for i, c in enumerate(syntax) if not c.isalnum())
    return m.group(1) + syntax[:at] + "\\" + syntax[at:]


def _prose(text: str) -> str:
    return "\n".join(LEADING_SYNTAX.sub(_escaped, line) for line in text.splitlines())


def _heading(level: int, text: str) -> str:
    if level > MAX_LEVEL:
        raise LevelTooDeep(f"heading {text!r} would sit at level {level}, past {MAX_LEVEL}")
    return f"{'#' * level} {' '.join(text.split())}"


def _code(block: Code) -> str:
    longest = max((len(m) for m in re.findall(r"`{3,}", block.text)), default=2)
    fence = "`" * (longest + 1)
    return f"{fence}{block.language or ''}\n{block.text.rstrip()}\n{fence}"


def _cell(text: str) -> str:
    return " ".join(text.split()).replace("|", "\\|")


def _table(block: Table) -> str:
    rows = block.rows
    if not rows:
        return ""
    if any(c.rowspan > 1 or c.colspan > 1 for row in rows for c in row) or len({len(r) for r in rows}) > 1:
        return _html_table(block)
    lines = ["| " + " | ".join(_cell(c.text) for c in rows[0]) + " |", "|" + "---|" * len(rows[0])]
    lines += ["| " + " | ".join(_cell(c.text) for c in row) + " |" for row in rows[1:]]
    return "\n".join(lines)


def _html_table(block: Table) -> str:
    out = ["<table>"]
    for row in block.rows:
        cells = []
        for c in row:
            tag = "th" if c.header else "td"
            spans = f' rowspan="{c.rowspan}"' if c.rowspan > 1 else ""
            spans += f' colspan="{c.colspan}"' if c.colspan > 1 else ""
            cells.append(f"<{tag}{spans}>{escape(' '.join(c.text.split()))}</{tag}>")
        out.append("<tr>" + "".join(cells) + "</tr>")
    out.append("</table>")
    return "\n".join(out)


def _list(block: ListBlock, indent: str = "") -> str:
    lines = []
    for i, item in enumerate(block.items):
        marker = f"{block.start + i}." if block.ordered else "-"
        lines.append(f"{indent}{marker} {' '.join(item.text.split())}")
        for child in item.children:
            lines.append(_list(child, indent + " " * (len(marker) + 1)))
    return "\n".join(lines)


# a figure is linked only when its image is a file in the bundle
def image_kept(image: str) -> bool:
    return re.fullmatch(r"[\w./-]+\.(png|jpe?g|gif|svg|webp)", image) is not None


# a figure whose image is not kept as a file yet is marked, since every image link in the bundle must resolve
def _figure(block: Figure) -> str:
    if image_kept(block.image):
        return f"![{block.alt}]({block.image})"
    page = f" page {block.where.page}" if block.where is not None else ""
    return f"<!-- figure{page}: image not kept yet -->"


def _note(block: Note) -> str:
    body = f"**{block.label}:** {block.text.strip()}".splitlines()
    return "\n".join(f"> {line}" if line else ">" for line in body)


def _block(block, chapter_level: int) -> str | None:
    match block:
        case Heading():
            return _heading(chapter_level + block.level, block.text)
        case Paragraph():
            return _prose(block.text.strip())
        case Code():
            return _code(block)
        case Table():
            return _table(block)
        case ListBlock():
            return _list(block)
        case Figure():
            return _figure(block)
        case Caption():
            return f"*{' '.join(block.text.split())}*"
        case Note():
            return _note(block)
        case Footnote():
            return f"[^{block.mark}]: {' '.join(block.text.split())}"
        case Formula():
            return f"$$\n{block.latex.strip()}\n$$"
        case PageMarker():
            return None
    raise TypeError(f"no Markdown for {type(block).__name__}")


def body(blocks: list, chapter_level: int) -> str:
    return "\n\n".join(text for block in blocks if (text := _block(block, chapter_level)))


# the book title is #, so a chapter at toc level 1 is ## and its inner headings go below it
def chapter(ch: Chapter) -> str:
    level = ch.level + 1
    head = [f"<!-- chapter ord={ch.ord} pages={ch.first_page}-{ch.last_page} role={ch.role} -->",
            _heading(level, ch.title)]
    return "\n\n".join([*head, body(ch.blocks, level)]) if ch.blocks else "\n\n".join(head)


# the book: its title on top, then its chapters' Markdown in order
def book(title: str, chapters: list[str]) -> str:
    return "\n\n".join([_heading(1, title), *chapters]) + "\n"


def document(doc: Document) -> str:
    return book(doc.title, [chapter(ch) for ch in doc.chapters])
