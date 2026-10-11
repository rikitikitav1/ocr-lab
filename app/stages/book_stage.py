# a book's stage read from its current versions, so a stage collected again never moves it back
from orm.catalogue import Book, MetadataVersion, TocVersion

from stages import versions


def settle(session, book_id: int) -> None:
    has = {kind: versions.current(session, model, book_id) is not None
           for kind, model in (("toc", TocVersion), ("metadata", MetadataVersion))}
    book = session.get(Book, book_id)
    book.stage = "ready" if has["toc"] else "metadata" if has["metadata"] else book.stage
