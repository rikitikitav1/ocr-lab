from pathlib import Path

import settings
from stages import assemble
from stages.elements import collect

SOURCES = "stages/structure/sources/__init__.py"

# each book-level list is keyed by the files its make reads; a module that moves rewrites its row here
SLOTS, NOTES = "elements/running_heads/slots.py", "elements/footnotes/book.py"
MADE_BY = {"running_heads.json": ["elements/running_heads/book.py", SLOTS, SOURCES],
           "slot_lines.json": [SLOTS, SOURCES],
           "note_lines.json": [NOTES, SLOTS, "stages/elements/page.py", SOURCES],
           "captions.json": ["elements/captions/book.py", SOURCES],
           "series_captions.json": ["elements/captions/book.py", SOURCES]}


def test_each_book_level_list_is_keyed_by_the_modules_that_make_it():
    made_by = {name: [Path(m.__file__).relative_to(settings.APP_DIR).as_posix() for m in modules]
               for name, modules in assemble.LIST_CODE.items()}
    assert made_by == MADE_BY


LAYOUT = "stages/elements/collect.py"
BODY = "elements/body.py"
READS = {"page": [LAYOUT, "stages/elements/page.py", SLOTS, NOTES, BODY, "numerals.py", SOURCES, "text_layer.py"],
         "headings": [LAYOUT, "elements/headings/book.py", "stages/elements/page.py", SLOTS, NOTES, BODY, "numerals.py",
                      SOURCES, "assembly/titles.py"]}


def test_each_layout_is_keyed_by_the_modules_it_reads():
    reads = {kind: [Path(m.__file__).relative_to(settings.APP_DIR).as_posix() for m in modules]
             for kind, modules in collect.READS.items()}
    assert reads == READS
    assert collect.code_hash("page") != collect.code_hash("headings")
