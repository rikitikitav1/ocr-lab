import pdf
import text_layer
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

# body rows give the file enough letter and word gaps for its spacing to be read
BODY = [("plain body text of the page with several words in it", 0.0)] * 6


# a tracked row is set letter by letter, as a book's spaced heading is; PDFium then puts a space after each letter
def _book(path, rows):
    c = canvas.Canvas(str(path), pagesize=A4)
    y = 780
    for text, spacing in rows + BODY:
        c.setFont("Helvetica", 12)
        if not spacing:
            c.drawString(72, y, text)
        else:
            x = 72
            for ch in text:
                if ch == " ":
                    x += 4 * spacing
                    continue
                c.drawString(x, y, ch)
                x += c.stringWidth(ch, "Helvetica", 12) + spacing
        y -= 30
    c.save()
    return path


def test_a_letter_spaced_heading_reads_whole_and_a_plain_row_stays(tmp_path):
    path = _book(tmp_path / "a.pdf", [("CHAPTER ONE", 2.5), ("plain body text of the page", 0.0),
                                      ("a b c d are four letters", 0.0)])
    rows = text_layer.page_texts(path)[0].split("\n")
    assert rows[0].strip() == "CHAPTER ONE" and "plain body text of the page" in rows[1]
    assert "a b c d are four letters" in rows[2]


def test_the_reader_names_the_rows_it_joined(tmp_path):
    path = _book(tmp_path / "b.pdf", [("SPACED", 2.5), ("normal words here", 0.0)])
    assert text_layer.page_layers(path)[0].rows == [("S P A C E D", "SPACED")]
    assert text_layer.page_layers(path)[0].as_read.startswith("S P A C E D")


def test_a_row_with_a_math_symbol_is_left_as_read(tmp_path):
    path = _book(tmp_path / "c.pdf", [("x ∈ SET", 2.5)])
    assert text_layer.page_layers(path)[0].rows == []


def test_an_engine_block_holding_the_row_takes_it_joined_whatever_its_own_spacing():
    from assembly import passes
    from document.model import Code, Heading, PageMarker, Paragraph

    rows = {1: [("9.1.6. О т о м и к о з", "9.1.6. Отомикоз")]}
    blocks = [PageMarker(book_page=5, file_ord=0, file_page=1),
              Heading(text="9.1.6. О томикоз", level=3, level_source="mineru"),
              Paragraph(text="Отомикоз is treated"), Code(text="О т о м и к о з")]
    got, n = passes.respaced(blocks, rows)
    assert n == 1 and got[1].text == "9.1.6. Отомикоз" and got[2] is blocks[2] and got[3] is blocks[3]


def test_an_engine_heading_already_better_spaced_than_the_row_keeps_its_own_text():
    from assembly import passes
    from document.model import Heading, PageMarker

    rows = {1: [("8 .1. О С Т Р Ы Й", "8 .1. ОСТРЫЙ")]}
    blocks = [PageMarker(book_page=5, file_ord=0, file_page=1),
              Heading(text="8.1. ОСТРЫЙ", level=3, level_source="mineru")]
    got, n = passes.respaced(blocks, rows)
    assert n == 0 and got[1].text == "8.1. ОСТРЫЙ"


def test_a_file_whose_letter_gaps_stand_well_under_its_word_gaps_is_read_with_its_spacing_joined(tmp_path):
    path = _book(tmp_path / "d.pdf", [("SPACED", 2.5)])
    letters, words = text_layer.spacing_gaps(path)
    assert letters < 0.5 * words and text_layer.spacing_fits(path)


def test_a_page_reads_the_same_before_and_after_the_process_renders_it(tmp_path):
    path = _book(tmp_path / "e.pdf", [("SPACED HEADING", 2.5)])
    before = text_layer.page_layers(path)
    pdf.page_crop(path, 0, (0, 0, 1, 1))
    assert text_layer.page_layers(path) == before


def test_a_split_by_an_f_is_checked_against_the_words_the_book_sets_solid(tmp_path):
    path = _book(tmp_path / "f.pdf", [("a definition here", 0.0)])
    solid = text_layer.solid_words(path)
    assert text_layer._halves("the def inition of", 7) == ("def", "inition")
    assert text_layer._joins(("def", "inition"), solid)
    assert not text_layer._joins(("if", "it"), solid)
    assert not text_layer._joins(("plain", "body"), solid + text_layer.Counter({"plainbody": 1}))


def test_the_lines_of_a_page_join_with_the_same_words_the_page_s_text_does(tmp_path, monkeypatch):
    path = _book(tmp_path / "g.pdf", [("SPACED HEADING", 2.5)])
    seen = []
    real = text_layer._joined

    def joined(textpage, spaced=False, solid=None):
        seen.append((spaced, solid))
        return real(textpage, spaced, solid)

    monkeypatch.setattr(text_layer, "_joined", joined)
    text_layer.page_texts(path)
    text_layer.page_lines(path)
    assert len(seen) == 2 and seen[0] == seen[1] and seen[0][1] == text_layer.solid_words(path)
