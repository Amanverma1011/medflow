"""Document ingestion: validate -> extract -> clean -> chunk -> metadata -> embed -> store."""
import hashlib
import io
import logging
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.ai.providers import get_embedder
from app.core.clock import now
from app.core.config import settings
from app.core.errors import AppError
from app.models import Document, DocumentChunk, DocumentEmbedding

log = logging.getLogger("medflow.rag.ingest")

ALLOWED_EXTENSIONS = {".pdf", ".txt", ".md", ".docx"}
EMBED_BATCH = 64


@dataclass
class ChunkDraft:
    content: str
    page: int
    section: str


# --------------------------------------------------------------------------- validation
def validate_upload(filename: str, data: bytes) -> str:
    """Return the normalised extension or raise a 4xx. Checks type by content, not just by name."""
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise AppError(400, "Unsupported file type. Upload a PDF, DOCX, TXT or Markdown file.")
    if not data:
        raise AppError(400, "The uploaded file is empty.")
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise AppError(413, f"File is larger than the {settings.max_upload_mb} MB limit.")
    if ext == ".pdf" and not data.startswith(b"%PDF-"):
        raise AppError(400, "The file does not look like a valid PDF.")
    if ext == ".docx" and not (data.startswith(b"PK") and zipfile.is_zipfile(io.BytesIO(data))):
        raise AppError(400, "The file does not look like a valid DOCX document.")
    if ext in {".txt", ".md"}:
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            raise AppError(400, "Text files must be UTF-8 encoded.")
    return ext


def safe_filename(filename: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", Path(filename).name)[:120] or "document"


# --------------------------------------------------------------------------- extraction
def extract(data: bytes, ext: str) -> list[tuple[int, str]]:
    """Return [(page_number, text)]. Formats without pages yield a single page 1."""
    if ext == ".pdf":
        from pypdf import PdfReader
        return [(i, page.extract_text() or "") for i, page in enumerate(PdfReader(io.BytesIO(data)).pages, 1)]
    if ext == ".docx":
        from docx import Document as Docx
        blocks = []
        for p in Docx(io.BytesIO(data)).paragraphs:
            if text := p.text.strip():
                blocks.append(f"## {text}" if p.style.name.lower().startswith(("heading", "title")) else text)
        return [(1, "\n\n".join(blocks))]
    return [(1, data.decode("utf-8"))]


def clean(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace(" ", " ")
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)  # metadata comments are not content
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    text = re.sub(r"-\n(?=[a-z])", "", text)  # re-join words hyphenated across PDF lines
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# --------------------------------------------------------------------------- chunking
_MD_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*$")


def _heading(block: str) -> str | None:
    if "\n" in block:
        return None
    if m := _MD_HEADING.match(block):
        return m.group(1)
    # Plain-text / PDF headings: short, no terminal punctuation, title- or upper-case.
    if len(block) <= 70 and not block.endswith((".", ":", ",", ";")) and (block.istitle() or block.isupper()):
        return block.title() if block.isupper() else block
    return None


def _split_long(block: str, size: int) -> list[str]:
    if len(block) <= size:
        return [block]
    parts, current = [], ""
    for sentence in re.split(r"(?<=[.!?])\s+|\n", block):
        if current and len(current) + len(sentence) + 1 > size:
            parts.append(current)
            current = ""
        current = f"{current} {sentence}".strip()
    return parts + ([current] if current else [])


def _tail(text: str, overlap: int) -> str:
    """Last ~overlap characters, snapped forward to a sentence boundary."""
    if overlap <= 0 or len(text) <= overlap:
        return ""
    tail = text[-overlap:]
    cut = re.search(r"[.!?]\s+", tail)
    return tail[cut.end():] if cut else ""


def chunk_pages(pages: list[tuple[int, str]], size: int | None = None, overlap: int | None = None) -> list[ChunkDraft]:
    """Section-aware chunking: paragraphs are packed up to `size` characters and never
    cross a heading, with a sentence-aligned overlap carried between consecutive chunks."""
    size = size or settings.rag_chunk_chars
    overlap = settings.rag_chunk_overlap if overlap is None else overlap
    chunks: list[ChunkDraft] = []
    section, buffer, buffer_page = "", "", 1

    def flush(carry: bool) -> None:
        nonlocal buffer
        if buffer.strip():
            chunks.append(ChunkDraft(buffer.strip(), buffer_page, section))
        buffer = _tail(buffer, overlap) if carry else ""

    for page, text in pages:
        for block in re.split(r"\n\s*\n", clean(text)):
            block = block.strip()
            if not block:
                continue
            if (title := _heading(block)) is not None:
                flush(carry=False)
                section = title[:200]
                continue
            for piece in _split_long(block, size):
                if buffer and len(buffer) + len(piece) + 2 > size:
                    flush(carry=True)
                if not buffer.strip():
                    buffer_page = page
                buffer = f"{buffer}\n\n{piece}".strip()
    flush(carry=False)
    return chunks


def embedding_text(document_name: str, draft: ChunkDraft) -> str:
    """Prefix each chunk with its document and section so short chunks keep their topic."""
    return f"{document_name}. {draft.section}. {draft.content}"


# --------------------------------------------------------------------------- pipeline
async def ingest_document(db: Session, doc: Document, data: bytes) -> Document:
    """(Re)index one document. Failures are recorded on the row, not raised."""
    embedder = get_embedder()
    doc.status, doc.error = "processing", ""
    db.commit()
    try:
        ext = Path(doc.filename).suffix.lower()
        drafts = chunk_pages(extract(data, ext))
        if not drafts:
            raise ValueError("No readable text could be extracted from this file.")
        vectors: list[list[float]] = []
        for i in range(0, len(drafts), EMBED_BATCH):
            vectors += await embedder.embed([embedding_text(doc.name, d) for d in drafts[i:i + EMBED_BATCH]])

        db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == doc.id))
        for index, (draft, vector) in enumerate(zip(drafts, vectors)):
            db.add(DocumentChunk(
                document_id=doc.id, chunk_index=index, content=draft.content, page=draft.page,
                section=draft.section,
                meta={"document_id": doc.id, "document_name": doc.name, "page": draft.page,
                      "section": draft.section, "source_type": doc.source_type, "kb": doc.kb,
                      "uploaded_at": doc.uploaded_at.isoformat(), "version": doc.version},
                embedding=DocumentEmbedding(model=embedder.name, embedding=vector)))
        doc.status, doc.chunk_count = "indexed", len(drafts)
        doc.content_hash = hashlib.sha256(data).hexdigest()
        db.commit()
    except Exception as exc:
        db.rollback()
        doc.status, doc.error, doc.chunk_count = "failed", str(exc)[:400], 0
        db.commit()
        log.warning("ingestion failed for document %s: %s", doc.id, type(exc).__name__)
    return doc


def store_upload(doc_id: int, filename: str, data: bytes) -> str:
    folder = settings.data_dir / "uploads"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{doc_id}_{safe_filename(filename)}"
    path.write_bytes(data)
    return str(path)


_META = re.compile(r"<!--\s*(.*?)\s*-->", re.S)


def parse_front_matter(text: str, fallback_name: str) -> dict:
    """Seed documents carry `<!-- kb: hospital; source_type: policy; version: 1.2 -->` and an H1 title."""
    meta = {"name": fallback_name, "kb": "medical", "source_type": "patient_education", "version": "1.0"}
    if m := _META.search(text[:400]):
        for pair in m.group(1).split(";"):
            if ":" in pair:
                key, value = pair.split(":", 1)
                meta[key.strip()] = value.strip()
    if m := re.search(r"^#\s+(.+)$", text, re.M):
        meta["name"] = m.group(1).strip()
    return meta


async def ingest_directory(db: Session, folder: Path, uploaded_by: int | None = None) -> list[Document]:
    """Index every supported file in `folder`; files already indexed with the same hash are skipped."""
    existing = {d.filename: d for d in db.query(Document).all()}
    out = []
    for path in sorted(folder.iterdir()):
        if path.suffix.lower() not in ALLOWED_EXTENSIONS:
            continue
        data = path.read_bytes()
        doc = existing.get(path.name)
        if doc and doc.status == "indexed" and doc.content_hash == hashlib.sha256(data).hexdigest():
            out.append(doc)
            continue
        if doc is None:
            text = data.decode("utf-8", "ignore") if path.suffix.lower() in {".md", ".txt"} else ""
            meta = parse_front_matter(text, path.stem.replace("_", " ").replace("-", " ").title())
            doc = Document(name=meta["name"], filename=path.name, kb=meta["kb"], source_type=meta["source_type"],
                           version=meta["version"], storage_path=str(path), uploaded_by=uploaded_by,
                           uploaded_at=now())
            db.add(doc)
            db.commit()
        out.append(await ingest_document(db, doc, data))
    return out
