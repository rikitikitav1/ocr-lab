# every id a door is given must be a book, or the door names the ones that are not before it queues anything
from orm.catalogue import Book
from sqlalchemy import select


def check_books(session, ids: list[int]) -> None:
    found = set(session.scalars(select(Book.id).where(Book.id.in_(ids))))
    if missing := sorted(set(ids) - found):
        raise LookupError(f"no books {missing}")
