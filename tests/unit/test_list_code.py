from pathlib import Path

import settings
from stages import assemble

SOURCES = "stages/structure/sources/__init__.py"

# each book-level list is keyed by the files its make reads; a module that moves rewrites its row here
MADE_BY = {"running_heads.json": ["elements/running_heads/book.py", "stages/layout/page.py", SOURCES],
           "slot_lines.json": ["stages/layout/page.py", SOURCES],
           "note_lines.json": ["elements/footnotes/book.py", "stages/layout/page.py", SOURCES],
           "captions.json": ["elements/captions/book.py", SOURCES],
           "series_captions.json": ["elements/captions/book.py", SOURCES]}


def test_each_book_level_list_is_keyed_by_the_modules_that_make_it():
    made_by = {name: [Path(m.__file__).relative_to(settings.APP_DIR).as_posix() for m in modules]
               for name, modules in assemble.LIST_CODE.items()}
    assert made_by == MADE_BY
