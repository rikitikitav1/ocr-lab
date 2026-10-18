import pdf
import text_layer


def _laid(parts, gaps, dy=0.0):
    text, box, made, x = "", [], [], 0.0
    for k, part in enumerate(parts):
        if k:
            text += "\r\n"
            box += [None, None]
            made += [True, True]
            x += gaps[k - 1]
        for ch in part:
            if ch == " ":
                text, box, made, x = text + ch, box + [None], made + [False], x + 3.0
                continue
            bottom = -dy if k % 2 else 0.0
            text += ch
            box.append((x, bottom, x + 5.0, bottom + 7.0))
            made.append(False)
            x += 5.4
    return text, box, made


def test_a_break_inside_a_word_on_one_row_is_undone():
    text, box, made = _laid(["Север", "е уступае", "т мест", "о"], [0.4, 0.4, 0.4], dy=0.5)
    assert text_layer.join_breaks(text, box, made) == "Севере уступает место"


def test_a_break_with_a_word_gap_or_a_new_row_stays():
    text, box, made = _laid(["first line", "next"], [3.5])
    assert text_layer.join_breaks(text, box, made) == text
    text, box, made = _laid(["first line", "next"], [0.4], dy=9.0)
    assert text_layer.join_breaks(text, box, made) == text


class _TextPage:
    raw = None

    def __init__(self, text, box):
        self.text, self.box = text, box

    def get_text_range(self):
        return self.text

    def count_chars(self):
        return len(self.text)

    def get_charbox(self, i):
        return self.box[i]


def test_lines_join_a_break_inside_a_word_and_keep_each_line_on_its_own_glyphs(monkeypatch):
    text, box, made = _laid(["Север", "е"], [0.4])
    text, box, made = text + "\r\nЮг", box + [None, None, (40.0, -20.0, 45.0, -13.0), (45.4, -20.0, 50.4, -13.0)], \
        made + [True, True, False, False]
    monkeypatch.setattr(pdf.pdfium_raw, "FPDFText_IsGenerated", lambda raw, i: made[i])
    monkeypatch.setattr(text_layer, "_char_style",
                        lambda textpage, i: (12.0 if text[i] in "Юг" else 10.0, False, False))
    page = type("Page", (), {"get_height": lambda self: 100.0})()
    assert text_layer._lines(page, _TextPage(text, box)) == [text_layer.Line("Севере", 0.0, 93.0, 10.0, False),
                                                      text_layer.Line("Юг", 40.0, 113.0, 12.0, False)]
