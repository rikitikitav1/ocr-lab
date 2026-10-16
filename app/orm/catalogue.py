from datetime import datetime
from enum import StrEnum

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from orm.db import Base


class Book(Base):
    __tablename__ = "books"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    sha256: Mapped[str] = mapped_column(Text, unique=True)
    pages: Mapped[int | None] = mapped_column(Integer)
    text_layer: Mapped[dict | None] = mapped_column(JSONB)
    has_bookmarks: Mapped[bool | None] = mapped_column(Boolean)
    has_printed_contents: Mapped[bool | None] = mapped_column(Boolean)
    structure_sources: Mapped[dict | None] = mapped_column(JSONB)
    stage: Mapped[str] = mapped_column(Text, default="uploaded")
    result_run_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("runs.id"))
    knobs: Mapped[dict] = mapped_column(JSONB, default=dict)
    page_offset: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BookFile(Base):
    __tablename__ = "book_files"
    book_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("books.id"), primary_key=True)
    ord: Mapped[int] = mapped_column(Integer, primary_key=True)
    sha256: Mapped[str] = mapped_column(Text)
    file_path: Mapped[str] = mapped_column(Text)
    file_name: Mapped[str] = mapped_column(Text)
    pages: Mapped[int] = mapped_column(Integer)
    first_page: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MetadataVersion(Base):
    __tablename__ = "metadata_versions"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    book_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("books.id"))
    version: Mapped[int] = mapped_column(Integer)
    input_hash: Mapped[str] = mapped_column(Text)
    job_id: Mapped[int | None] = mapped_column(BigInteger)
    current: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MetadataField(Base):
    __tablename__ = "metadata_fields"
    metadata_version_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("metadata_versions.id"), primary_key=True)
    name: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[object | None] = mapped_column(JSONB)
    source: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)
    attempts: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StructureVersion(Base):
    __tablename__ = "structure_versions"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    book_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("books.id"))
    version: Mapped[int] = mapped_column(Integer)
    input_hash: Mapped[str] = mapped_column(Text)
    job_id: Mapped[int | None] = mapped_column(BigInteger)
    current: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    depth: Mapped[int] = mapped_column(Integer, default=0)


class LayoutVersion(Base):
    __tablename__ = "layout_versions"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    book_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("books.id"))
    kind: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer)
    input_hash: Mapped[str] = mapped_column(Text)
    job_id: Mapped[int | None] = mapped_column(BigInteger)
    current: Mapped[bool] = mapped_column(Boolean, default=False)
    structure_version_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("structure_versions.id"))
    layout: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StructureNode(Base):
    __tablename__ = "nodes"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    structure_version_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("structure_versions.id"))
    ord: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(Text)
    level: Mapped[int] = mapped_column(Integer)
    level_source: Mapped[str] = mapped_column(Text)
    first_page: Mapped[int | None] = mapped_column(Integer)
    last_page: Mapped[int | None] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(Text)
    votes: Mapped[dict] = mapped_column(JSONB, default=dict)
    parent_ord: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Profile(Base):
    __tablename__ = "profiles"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    book_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("books.id"))
    preset: Mapped[str] = mapped_column(Text)
    values: Mapped[dict] = mapped_column(JSONB)
    piece_overrides: Mapped[dict] = mapped_column(JSONB, default=dict)
    sha256: Mapped[str] = mapped_column(Text)
    parent_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("profiles.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# a run's life: queued, then running through its stages, then done, waiting for attention or cancelled
class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    ATTENTION = "needs_attention"
    CANCELLED = "cancelled"


class RunStage(StrEnum):
    ASSEMBLE = "assemble"
    METRICS = "metrics"
    ATTENTION = "attention"
    DONE = "done"
    CANCELLED = "cancelled"


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    book_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("books.id"))
    profile_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("profiles.id"))
    metadata_version_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("metadata_versions.id"))
    structure_version_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("structure_versions.id"))
    format: Mapped[str] = mapped_column(Text, default="markdown")
    dir: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="queued")
    stage: Mapped[str | None] = mapped_column(Text)
    code_hash: Mapped[str | None] = mapped_column(Text)
    engine_builds: Mapped[dict] = mapped_column(JSONB, default=dict)
    bundle_dir: Mapped[str | None] = mapped_column(Text)
    reading_level: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Piece(Base):
    __tablename__ = "pieces"
    run_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("runs.id"), primary_key=True)
    ord: Mapped[int] = mapped_column(Integer, primary_key=True)
    node_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("nodes.id"))
    status: Mapped[str] = mapped_column(Text, default="pending")
    engine: Mapped[str | None] = mapped_column(Text)
    checks: Mapped[dict] = mapped_column(JSONB, default=dict)
    errors: Mapped[list] = mapped_column(JSONB, default=list)
    seconds: Mapped[float | None] = mapped_column(Float)
    gpu_seconds: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Artifact(Base):
    __tablename__ = "artifacts"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("runs.id"))
    metadata_version_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("metadata_versions.id"))
    structure_version_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("structure_versions.id"))
    book_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("books.id"))
    stage: Mapped[str] = mapped_column(Text)
    piece_ord: Mapped[int | None] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(Text)
    path: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(Text)
    input_hash: Mapped[str] = mapped_column(Text)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict)
    heavy: Mapped[bool] = mapped_column(Boolean, default=False)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ModelCall(Base):
    __tablename__ = "model_calls"
    request_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    provider: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(Text)
    params: Mapped[dict] = mapped_column(JSONB, default=dict)
    response_path: Mapped[str] = mapped_column(Text)
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
