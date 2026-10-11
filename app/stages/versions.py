# a book's versions of a stage (metadata, toc): the current one, and a new one made current under the book's lock
from orm.catalogue import Book
from sqlalchemy import func, select, update


def current(session, model, book_id: int):
    return session.scalar(select(model).where(model.book_id == book_id, model.current))


# the book row is locked for the whole write, so two writers never take the same version number
def lock_book(session, book_id: int) -> None:
    session.execute(select(Book.id).where(Book.id == book_id).with_for_update())


def new(session, model, book_id: int, input_hash: str, job_id: int | None):
    number = (session.scalar(select(func.max(model.version)).where(model.book_id == book_id)) or 0) + 1
    session.execute(update(model).where(model.book_id == book_id).values(current=False))
    version = model(book_id=book_id, version=number, input_hash=input_hash, job_id=job_id, current=True)
    session.add(version)
    session.flush()
    return version
