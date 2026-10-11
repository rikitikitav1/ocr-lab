# the PDF outline of each file, its pages moved to the file's place in the book
import pdf
import settings
from orm.catalogue import BookFile

from stages.toc.sources import Entry, SourceToc


def read(files: list[BookFile]) -> SourceToc:
    out = SourceToc("bookmarks")
    for f in files:
        for mark in pdf.outline(settings.DATA_DIR / f.file_path):
            if not mark["title"]:
                continue
            page = f.first_page + mark["page"] if mark["page"] is not None else None
            out.entries.append(Entry(mark["title"], mark["level"], page, evidence=f"outline of file {f.ord}",
                                     verified=page is not None))
    return out
