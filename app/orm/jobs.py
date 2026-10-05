from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from orm.db import Base


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(Text)
    lane: Mapped[str] = mapped_column(Text)
    parent_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("jobs.id"))
    run_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("runs.id"))
    book_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("books.id"))
    options: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(Text, default="new")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    deferred_seconds: Mapped[int] = mapped_column(Integer, default=0)
    reclaims: Mapped[int] = mapped_column(Integer, default=0)
    apply_since: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    waiting_because: Mapped[dict | None] = mapped_column(JSONB)
    code_hash: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict | None] = mapped_column(JSONB)
    error: Mapped[dict | None] = mapped_column(JSONB)
    elapsed: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
