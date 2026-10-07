from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import CheckConstraint, Computed, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.clock import now
from app.core.config import settings
from app.core.db import Base
from app.models.hospital import _in

DOCUMENT_STATUSES = ("uploaded", "processing", "indexed", "failed", "archived")
KNOWLEDGE_BASES = ("medical", "hospital")


class AIConversation(Base):
    __tablename__ = "ai_conversations"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    assistant: Mapped[str] = mapped_column(String(12), default="medical")
    title: Mapped[str] = mapped_column(String(120), default="New conversation")
    created_at: Mapped[datetime] = mapped_column(default=now)
    updated_at: Mapped[datetime] = mapped_column(default=now, onupdate=now)


class AIMessage(Base):
    __tablename__ = "ai_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("ai_conversations.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(10))
    content: Mapped[str] = mapped_column(Text)
    sources: Mapped[list] = mapped_column(JSONB, default=list)
    confidence: Mapped[float | None]
    safety_category: Mapped[str | None] = mapped_column(String(32))
    knowledge_scope: Mapped[str | None] = mapped_column(String(12))
    feedback: Mapped[int] = mapped_column(default=0)  # -1 / 0 / +1
    created_at: Mapped[datetime] = mapped_column(default=now)
    __table_args__ = (CheckConstraint(_in("role", ("user", "assistant"))),)


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    filename: Mapped[str] = mapped_column(String(200))
    kb: Mapped[str] = mapped_column(String(12), default="medical", index=True)
    source_type: Mapped[str] = mapped_column(String(40), default="hospital_guideline")
    version: Mapped[str] = mapped_column(String(16), default="1.0")
    status: Mapped[str] = mapped_column(String(12), default="uploaded")
    error: Mapped[str] = mapped_column(String(400), default="")
    chunk_count: Mapped[int] = mapped_column(default=0)
    is_active: Mapped[bool] = mapped_column(default=True)
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    storage_path: Mapped[str] = mapped_column(String(400), default="")
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    uploaded_at: Mapped[datetime] = mapped_column(default=now)
    chunks: Mapped[list["DocumentChunk"]] = relationship(cascade="all, delete-orphan", back_populates="document",
                                                         order_by="DocumentChunk.chunk_index")
    __table_args__ = (CheckConstraint(_in("status", DOCUMENT_STATUSES)), CheckConstraint(_in("kb", KNOWLEDGE_BASES)))


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    chunk_index: Mapped[int]
    content: Mapped[str] = mapped_column(Text)
    page: Mapped[int] = mapped_column(default=1)
    section: Mapped[str] = mapped_column(String(200), default="")
    meta: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    tsv = mapped_column(TSVECTOR, Computed("to_tsvector('english', coalesce(section, '') || ' ' || content)",
                                           persisted=True))
    document: Mapped[Document] = relationship(back_populates="chunks")
    embedding: Mapped["DocumentEmbedding"] = relationship(cascade="all, delete-orphan", uselist=False)
    __table_args__ = (UniqueConstraint("document_id", "chunk_index"),
                      Index("ix_document_chunks_tsv", "tsv", postgresql_using="gin"))


class DocumentEmbedding(Base):
    __tablename__ = "document_embeddings"
    id: Mapped[int] = mapped_column(primary_key=True)
    chunk_id: Mapped[int] = mapped_column(ForeignKey("document_chunks.id", ondelete="CASCADE"), unique=True)
    model: Mapped[str] = mapped_column(String(80))
    embedding = mapped_column(Vector(settings.vector_dimension))
    __table_args__ = (Index("ix_document_embeddings_hnsw", "embedding", postgresql_using="hnsw",
                            postgresql_ops={"embedding": "vector_cosine_ops"}),)


class AIPrediction(Base):
    __tablename__ = "ai_predictions"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    target: Mapped[str] = mapped_column(String(80))
    horizon: Mapped[str] = mapped_column(String(24))
    value: Mapped[float]
    unit: Mapped[str] = mapped_column(String(16))
    confidence: Mapped[float]
    factors: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(default=now, index=True)


class AIInsight(Base):
    __tablename__ = "ai_insights"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(48))  # stable rule id, used to refresh instead of duplicating
    title: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(10))
    category: Mapped[str] = mapped_column(String(24))
    confidence: Mapped[float]
    impact: Mapped[str] = mapped_column(String(200), default="")
    recommendation: Mapped[str] = mapped_column(Text)
    evidence: Mapped[list] = mapped_column(JSONB, default=list)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"))
    status: Mapped[str] = mapped_column(String(10), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(default=now)
    __table_args__ = (CheckConstraint(_in("severity", ("low", "medium", "high", "critical"))),
                      CheckConstraint(_in("status", ("active", "dismissed"))))
