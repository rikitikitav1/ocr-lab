# small PDFs built in the test, so every case says exactly what the file holds
from pathlib import Path

from reportlab.lib.pagesizes import A5
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

FONT = "Helvetica"
for candidate in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/TTF/DejaVuSans.ttf"):
    if Path(candidate).exists():
        pdfmetrics.registerFont(TTFont("DejaVu", candidate))
        FONT = "DejaVu"
        break

FILLER = "The quick brown fox jumps over the lazy dog while the stand counts characters on the page. " * 4


def build(path: Path, pages: list[dict]) -> Path:
    c = canvas.Canvas(str(path), pagesize=A5)
    for i, page in enumerate(pages):
        y = 520
        if page.get("bookmark"):
            c.bookmarkPage(f"p{i}")
            c.addOutlineEntry(page["bookmark"], f"p{i}", level=page.get("level", 0))
        if page.get("raster"):
            c.setFillGray(0.3)
            c.rect(40, 200, 300, 300, fill=1)
        # a line is its text, or a dict with its indent and font size
        for line in page.get("lines", []):
            spec = line if isinstance(line, dict) else {"text": line}
            y -= max(0, spec.get("size", 10) - 10)
            c.setFont(FONT, spec.get("size", 10))
            c.drawString(spec.get("x", 30), y, spec["text"])
            y -= max(14, spec.get("size", 10) + 4)
        c.showPage()
    c.save()
    return path


def text_page(*lines: str, bookmark: str | None = None) -> dict:
    return {"lines": [*lines, FILLER[:90], FILLER[90:180]], "bookmark": bookmark}


def raster_page() -> dict:
    return {"raster": True}


def contents_page() -> dict:
    return {"lines": [f"Chapter {n} The thing number {n} . . . . . . . . . . {n * 10}" for n in range(1, 9)]}


