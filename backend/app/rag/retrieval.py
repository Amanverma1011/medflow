"""Hybrid retrieval over pgvector (semantic) and PostgreSQL full-text search (keyword)."""
from dataclasses import asdict, dataclass

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Document, DocumentChunk, DocumentEmbedding


@dataclass
class Candidate:
    chunk_id: int
    document_id: int
    document: str
    kb: str
    source_type: str
    version: str
    section: str
    page: int
    content: str
    semantic: float = 0.0  # cosine similarity, clamped to [0, 1]
    keyword: float = 0.0  # raw ts_rank_cd
    keyword_norm: float = 0.0  # keyword / max keyword in the candidate set
    hybrid: float = 0.0
    rerank: float = 0.0

    def scores(self) -> dict:
        d = asdict(self)
        d.pop("content")
        return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in d.items()}


def _visible(kb: str | None):
    """Metadata filter: only active, indexed documents, optionally limited to one knowledge base."""
    conditions = [Document.is_active.is_(True), Document.status == "indexed"]
    if kb:
        conditions.append(Document.kb == kb)
    return conditions


def semantic_search(db: Session, query_vector: list[float], kb: str | None, limit: int) -> dict[int, float]:
    distance = DocumentEmbedding.embedding.cosine_distance(query_vector)
    rows = db.execute(
        select(DocumentEmbedding.chunk_id, distance.label("distance"))
        .join(DocumentChunk, DocumentChunk.id == DocumentEmbedding.chunk_id)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(*_visible(kb)).order_by(distance).limit(limit)).all()
    return {r.chunk_id: max(0.0, min(1.0, 1.0 - float(r.distance))) for r in rows}


# Any query term may match (OR), ranking rewards chunks matching more of them close together.
_KEYWORD_SQL = text("""
    WITH q AS (
        SELECT to_tsquery('english',
                          NULLIF(replace(plainto_tsquery('english', :query)::text, '&', '|'), '')) AS tsq
    )
    SELECT c.id AS chunk_id, ts_rank_cd(c.tsv, q.tsq, 32) AS rank
    FROM document_chunks c
    JOIN documents d ON d.id = c.document_id, q
    WHERE q.tsq IS NOT NULL AND c.tsv @@ q.tsq
      AND d.is_active AND d.status = 'indexed' AND (CAST(:kb AS text) IS NULL OR d.kb = :kb)
    ORDER BY rank DESC
    LIMIT :limit
""")


def keyword_search(db: Session, query: str, kb: str | None, limit: int) -> dict[int, float]:
    rows = db.execute(_KEYWORD_SQL, {"query": query, "kb": kb, "limit": limit}).all()
    return {r.chunk_id: float(r.rank) for r in rows}


def hybrid_search(db: Session, query: str, query_vector: list[float], kb: str | None = None,
                  top_k: int | None = None) -> list[Candidate]:
    """Hybrid score = alpha * semantic_similarity + beta * normalised_keyword_score."""
    top_k = top_k or settings.rag_top_k
    semantic = semantic_search(db, query_vector, kb, top_k)
    keyword = keyword_search(db, query, kb, top_k)
    ids = set(semantic) | set(keyword)
    if not ids:
        return []
    max_keyword = max(keyword.values(), default=0.0) or 1.0
    rows = db.execute(
        select(DocumentChunk, Document).join(Document, Document.id == DocumentChunk.document_id)
        .where(DocumentChunk.id.in_(ids))).all()
    candidates = []
    for chunk, doc in rows:
        c = Candidate(chunk.id, doc.id, doc.name, doc.kb, doc.source_type, doc.version, chunk.section, chunk.page,
                      chunk.content, semantic=semantic.get(chunk.id, 0.0), keyword=keyword.get(chunk.id, 0.0))
        c.keyword_norm = c.keyword / max_keyword
        c.hybrid = settings.rag_alpha * c.semantic + settings.rag_beta * c.keyword_norm
        candidates.append(c)
    return sorted(candidates, key=lambda c: -c.hybrid)[:top_k]
