import text_layer
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

PROSE = "a proportional face gives every letter its own advance, wide m and narrow i"
CODE = "for (int i = 0; i < count; i++) { total += values[i]; }"


def _book(path, rows, pages=6, turned=False):
    c = canvas.Canvas(str(path), pagesize=A4)
    for _ in range(pages):
        y = 780
        for face, text in rows:
            c.setFont(face, 10)
            if turned:
                c.saveState()
                c.translate(300, 100)
                c.rotate(90)
                c.drawString(0, 0, text)
                c.restoreState()
            else:
                c.drawString(72, y, text)
            y -= 20
        c.showPage()
    c.save()
    return path


def test_a_monospace_face_is_found_and_its_share_counted(tmp_path):
    got = text_layer.monospace([_book(tmp_path / "a.pdf", [("Helvetica", PROSE), ("Courier", CODE)])])
    assert [f["face"] for f in got["faces"]] == ["Courier"] and got["faces"][0]["spread"] == 0
    assert 0.25 < got["share"] < 0.5 and got["pages"] == 6


def test_proportional_text_has_no_monospace_share(tmp_path):
    got = text_layer.monospace([_book(tmp_path / "a.pdf", [("Helvetica", PROSE), ("Times-Roman", PROSE)])])
    assert got["faces"] == [] and got["share"] == 0


def test_turned_text_is_left_out(tmp_path):
    got = text_layer.monospace([_book(tmp_path / "a.pdf", [("Courier", CODE)], turned=True)])
    assert got["faces"] == [] and got["share"] == 0
