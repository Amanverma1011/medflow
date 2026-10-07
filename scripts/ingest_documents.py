"""Ingest knowledge documents into pgvector: extract -> clean -> chunk -> embed -> store.

    python scripts/ingest_documents.py                 # data/documents
    python scripts/ingest_documents.py path/to/folder

Unchanged files (same SHA-256) that are already indexed are skipped.
"""
import asyncio
import sys
from pathlib import Path

import _bootstrap  # noqa: F401
from app.ai.providers import get_embedder
from app.core.config import settings
from app.core.db import SessionLocal
from app.rag.ingest import ingest_directory


async def main() -> None:
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else settings.data_dir / "documents"
    print(f"Embedding provider: {get_embedder().name}")
    with SessionLocal() as db:
        for doc in await ingest_directory(db, folder):
            detail = f"{doc.chunk_count} chunks" if doc.status == "indexed" else doc.error
            print(f"  [{doc.status:<8}] {doc.kb:<8} {doc.name}  ({detail})")


if __name__ == "__main__":
    asyncio.run(main())
