"""Medical Assistant (RAG chat), knowledge base management, and the RAG debugger."""
import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai import safety
from app.ai.providers import ProviderError, get_embedder, get_llm, get_reranker
from app.core.clock import now
from app.core.config import settings
from app.core.db import SessionLocal, get_db
from app.core.errors import AppError
from app.core.ratelimit import rate_limit
from app.models import AIConversation, AIMessage, Document, DocumentChunk, User
from app.rag import evaluate, ingest, pipeline
from app.schemas.requests import ChatRequest, DocumentUpdate, IngestRequest, MessageFeedback, QuestionRequest
from app.security import audit
from app.security.auth import require

log = logging.getLogger("medflow.rag")
router = APIRouter(prefix="/rag", tags=["rag"])
chat_limit = Depends(rate_limit("chat", 30, 60))
SUGGESTIONS = ["What is hypertension?", "How should I prepare for an MRI?", "What does HbA1c mean?",
               "When should I seek urgent care?", "How do I prepare for a blood test?",
               "Where is the radiology department?", "What are the visiting hours?"]


# ------------------------------------------------------------------------------- chat
def _conversation(db: Session, user: User, body: ChatRequest) -> tuple[AIConversation, str | None]:
    """Load (or start) the caller's conversation and return it with the previous user question."""
    if body.conversation_id:
        conv = db.get(AIConversation, body.conversation_id)
        if conv is None or conv.user_id != user.id:
            raise AppError(404, "Conversation not found.")
        previous = db.scalar(select(AIMessage.content).where(
            AIMessage.conversation_id == conv.id, AIMessage.role == "user").order_by(AIMessage.id.desc()))
    else:
        conv = AIConversation(user_id=user.id, title=body.message[:60])
        db.add(conv)
        db.flush()
        previous = None
    db.add(AIMessage(conversation_id=conv.id, role="user", content=body.message))
    return conv, previous


def _store_answer(db: Session, conversation_id: int, result: pipeline.RagResult) -> AIMessage:
    message = AIMessage(conversation_id=conversation_id, role="assistant", content=result.answer,
                        sources=result.sources, confidence=result.confidence,
                        safety_category=result.safety_category, knowledge_scope=result.knowledge_scope)
    db.add(message)
    if conv := db.get(AIConversation, conversation_id):
        conv.updated_at = now()
    return message


def _audit_escalation(db: Session, request: Request, user: User, category: str) -> None:
    # Only the fact of an escalation is recorded, never what the user wrote.
    if category in {"EMERGENCY", "SELF_HARM"}:
        audit.record(db, request, user, "chat.escalation", "ai_conversation", detail=category)


@router.post("/chat", dependencies=[chat_limit])
async def chat(body: ChatRequest, request: Request, user: User = Depends(require("chat:use")),
               db: Session = Depends(get_db)):
    conv, previous = _conversation(db, user, body)
    try:
        _turn, result = await pipeline.answer(db, body.message, previous)
    except ProviderError as exc:
        log.error("AI provider failure: %s", exc)
        raise AppError(502, "The AI service is temporarily unavailable. Please try again.", "ai_unavailable")
    message = _store_answer(db, conv.id, result)
    _audit_escalation(db, request, user, result.safety_category)
    db.commit()
    return {"conversation_id": conv.id, "message_id": message.id, **asdict(result)}


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


@router.post("/chat/stream", dependencies=[chat_limit])
async def chat_stream(body: ChatRequest, request: Request, user: User = Depends(require("chat:use")),
                      db: Session = Depends(get_db)):
    """Server-Sent Events: `meta` (classification + retrieved sources), `token`*, then `done` (validated answer)."""
    conv, previous = _conversation(db, user, body)
    try:
        turn = await pipeline.prepare(db, body.message, previous)
    except ProviderError as exc:
        log.error("AI provider failure: %s", exc)
        raise AppError(502, "The AI service is temporarily unavailable. Please try again.", "ai_unavailable")
    _audit_escalation(db, request, user, turn.safety.category)
    db.commit()
    conversation_id = conv.id

    async def events():
        yield _sse("meta", {"conversation_id": conversation_id, "safety_category": turn.safety.category,
                            "knowledge_scope": turn.scope, "confidence": turn.confidence,
                            "sources": pipeline._sources(turn, set()), "demo_mode": get_llm().is_demo})
        generated = ""
        try:
            async for token in pipeline.stream_tokens(turn):
                generated += token
                yield _sse("token", {"t": token})
        except Exception as exc:  # provider dropped mid-stream
            log.error("stream failed: %s", type(exc).__name__)
            yield _sse("error", {"message": "The AI service stopped responding. Please try again."})
            return
        # The stream already included any safety prefix; finalize() expects the raw generation.
        raw = generated[len(turn.prefix):] if turn.prompt and turn.prefix else generated
        result = pipeline.finalize(turn, raw)
        with SessionLocal() as session:  # the request-scoped session is closed once streaming starts
            message = _store_answer(session, conversation_id, result)
            session.commit()
            yield _sse("done", {"conversation_id": conversation_id, "message_id": message.id, **asdict(result)})

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/status")
def status(_: User = Depends(require("chat:use")), db: Session = Depends(get_db)):
    """Which providers are live. The UI uses this to label demo mode honestly."""
    llm = get_llm()
    return {"llm": llm.name, "llm_demo": llm.is_demo, "embedding": get_embedder().name,
            "embedding_demo": not settings.remote_embeddings, "reranker": get_reranker().name,
            "documents": db.scalar(select(func.count(Document.id)).where(Document.status == "indexed",
                                                                         Document.is_active.is_(True))),
            "chunks": db.scalar(select(func.count(DocumentChunk.id))), "suggestions": SUGGESTIONS,
            "disclaimer": safety.DISCLAIMER, "emergency_notice": safety.EMERGENCY_NOTICE}


@router.get("/conversations")
def conversations(user: User = Depends(require("chat:use")), db: Session = Depends(get_db)):
    items = db.scalars(select(AIConversation).where(AIConversation.user_id == user.id)
                       .order_by(AIConversation.updated_at.desc(), AIConversation.id.desc()).limit(50))
    return [{"id": c.id, "title": c.title, "updated_at": c.updated_at} for c in items]


def _own_conversation(db: Session, user: User, conversation_id: int) -> AIConversation:
    conv = db.get(AIConversation, conversation_id)
    if conv is None or conv.user_id != user.id:
        raise AppError(404, "Conversation not found.")
    return conv


@router.get("/conversations/{conversation_id}")
def conversation(conversation_id: int, user: User = Depends(require("chat:use")), db: Session = Depends(get_db)):
    conv = _own_conversation(db, user, conversation_id)
    messages = db.scalars(select(AIMessage).where(AIMessage.conversation_id == conv.id).order_by(AIMessage.id))
    return {"id": conv.id, "title": conv.title,
            "messages": [{"id": m.id, "role": m.role, "content": m.content, "sources": m.sources,
                          "confidence": m.confidence, "safety_category": m.safety_category,
                          "knowledge_scope": m.knowledge_scope, "feedback": m.feedback,
                          "created_at": m.created_at} for m in messages]}


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: int, user: User = Depends(require("chat:use")),
                        db: Session = Depends(get_db)):
    db.delete(_own_conversation(db, user, conversation_id))
    db.commit()


@router.post("/messages/{message_id}/feedback", status_code=204)
def message_feedback(message_id: int, body: MessageFeedback, user: User = Depends(require("chat:use")),
                     db: Session = Depends(get_db)):
    message = db.get(AIMessage, message_id)
    if message is None or message.role != "assistant":
        raise AppError(404, "Message not found.")
    _own_conversation(db, user, message.conversation_id)
    message.feedback = body.value
    db.commit()


@router.get("/sources/{chunk_id}")
def source(chunk_id: int, user: User = Depends(require("chat:use")), db: Session = Depends(get_db)):
    """The passage behind a citation. Archived or inactive documents are only visible to knowledge managers."""
    chunk = db.get(DocumentChunk, chunk_id)
    if chunk is None:
        raise AppError(404, "Source not found.")
    doc = chunk.document
    if not (doc.is_active and doc.status == "indexed") and "knowledge:manage" not in user.permissions:
        raise AppError(404, "Source not found.")
    return {"chunk_id": chunk.id, "content": chunk.content, "section": chunk.section, "page": chunk.page,
            "chunk_index": chunk.chunk_index, "metadata": chunk.meta,
            "document": {"id": doc.id, "name": doc.name, "kb": doc.kb, "source_type": doc.source_type,
                         "version": doc.version, "uploaded_at": doc.uploaded_at, "chunk_count": doc.chunk_count}}


# ------------------------------------------------------------------------------- knowledge base
def _document(d: Document) -> dict:
    return {"id": d.id, "name": d.name, "filename": d.filename, "kb": d.kb, "source_type": d.source_type,
            "version": d.version, "status": d.status, "error": d.error, "chunk_count": d.chunk_count,
            "is_active": d.is_active, "uploaded_at": d.uploaded_at,
            "embedding_status": "embedded" if d.status == "indexed" else "pending" if d.status in
            ("uploaded", "processing") else "none"}


def _get_document(db: Session, document_id: int) -> Document:
    doc = db.get(Document, document_id)
    if doc is None:
        raise AppError(404, "Document not found.")
    return doc


@router.get("/documents")
def list_documents(_: User = Depends(require("knowledge:manage")), db: Session = Depends(get_db)):
    return [_document(d) for d in db.scalars(select(Document).order_by(Document.kb, Document.name))]


@router.post("/documents", status_code=201)
async def upload_document(request: Request, file: UploadFile = File(...),
                          name: str = Form("", max_length=160),
                          kb: Literal["medical", "hospital"] = Form("medical"),
                          source_type: str = Form("hospital_guideline", max_length=40, pattern=r"^[a-z_]+$"),
                          version: str = Form("1.0", max_length=16, pattern=r"^[0-9A-Za-z.\-]+$"),
                          user: User = Depends(require("knowledge:manage")), db: Session = Depends(get_db)):
    """Upload -> validate -> extract -> clean -> chunk -> embed -> store. Returns the indexed document."""
    data = await file.read(settings.max_upload_mb * 1024 * 1024 + 1)
    filename = ingest.safe_filename(file.filename or "document")
    ingest.validate_upload(filename, data)
    doc = Document(name=name.strip() or Path(filename).stem.replace("_", " ").title(), filename=filename, kb=kb,
                   source_type=source_type, version=version, uploaded_by=user.id)
    db.add(doc)
    db.flush()
    doc.storage_path = ingest.store_upload(doc.id, filename, data)
    audit.record(db, request, user, "knowledge.upload", "document", doc.id, detail=f"{kb} · {filename}")
    db.commit()
    await ingest.ingest_document(db, doc, data)
    return _document(doc)


@router.post("/ingest")
async def reingest(body: IngestRequest, request: Request, user: User = Depends(require("knowledge:manage")),
                   db: Session = Depends(get_db)):
    """Re-index one document, or all of them (e.g. after changing the embedding model)."""
    docs = [_get_document(db, body.document_id)] if body.document_id else list(db.scalars(select(Document)))
    results = []
    for doc in docs:
        path = Path(doc.storage_path)
        if not path.is_file():
            doc.status, doc.error = "failed", "The original file is no longer available. Upload it again."
            db.commit()
        else:
            was_archived = doc.status == "archived"
            await ingest.ingest_document(db, doc, path.read_bytes())
            if was_archived and doc.status == "indexed":
                doc.status = "archived"
                db.commit()
        results.append(_document(doc))
    audit.record(db, request, user, "knowledge.reindex", "document", body.document_id,
                 detail=f"{len(results)} document(s)")
    db.commit()
    return results


@router.get("/documents/{document_id}")
def get_document(document_id: int, _: User = Depends(require("knowledge:manage")), db: Session = Depends(get_db)):
    doc = _get_document(db, document_id)
    return {**_document(doc), "chunks": [{"id": c.id, "index": c.chunk_index, "section": c.section,
                                          "page": c.page, "content": c.content} for c in doc.chunks]}


@router.patch("/documents/{document_id}")
def update_document(document_id: int, body: DocumentUpdate, request: Request,
                    user: User = Depends(require("knowledge:manage")), db: Session = Depends(get_db)):
    doc = _get_document(db, document_id)
    if body.archived is True:
        doc.status, doc.is_active = "archived", False
    elif body.archived is False and doc.status == "archived":
        doc.status, doc.is_active = ("indexed" if doc.chunk_count else "uploaded"), True
    if body.is_active is not None and doc.status != "archived":
        doc.is_active = body.is_active
    audit.record(db, request, user, "knowledge.update", "document", doc.id,
                 detail=f"status={doc.status} active={doc.is_active}")
    db.commit()
    return _document(doc)


@router.delete("/documents/{document_id}", status_code=204)
def delete_document(document_id: int, request: Request, user: User = Depends(require("knowledge:manage")),
                    db: Session = Depends(get_db)):
    doc = _get_document(db, document_id)
    uploads = (settings.data_dir / "uploads").resolve()
    path = Path(doc.storage_path).resolve() if doc.storage_path else None
    db.delete(doc)  # chunks and embeddings cascade
    audit.record(db, request, user, "knowledge.delete", "document", document_id, detail=doc.filename)
    db.commit()
    if path and path.is_file() and uploads in path.parents:  # never delete the bundled seed documents
        path.unlink()


# ------------------------------------------------------------------------------- observability
@router.post("/debug")
async def debug(body: QuestionRequest, _: User = Depends(require("rag:debug")), db: Session = Depends(get_db)):
    """Run the full pipeline for one question and return every intermediate result."""
    turn = await pipeline.prepare(db, body.question)
    generated = await get_llm().generate(turn.prompt) if turn.prompt else ""
    return pipeline.trace(turn, pipeline.finalize(turn, generated), generated)


@router.post("/evaluate")
async def run_evaluation(_: User = Depends(require("rag:debug")), db: Session = Depends(get_db)):
    return await evaluate.run(db)
