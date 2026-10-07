"""One entry point for loading the demo hospital: used by startup, the seed script and the admin button."""
import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analytics.insights import InsightEngine
from app.core.config import settings
from app.models import User
from app.rag.ingest import ingest_directory
from app.services import seed

log = logging.getLogger("medflow.bootstrap")


async def load_demo(db: Session, scale: float = 1.0) -> dict:
    counts = seed.run(db, scale=scale)
    documents = await ingest_directory(db, settings.data_dir / "documents")
    counts["knowledge_documents"] = sum(1 for d in documents if d.status == "indexed")
    counts["knowledge_chunks"] = sum(d.chunk_count for d in documents)
    counts["insights"] = len(InsightEngine(db).refresh(notify=True))
    log.info("demo hospital loaded: %s", counts)
    return counts


async def seed_if_empty(db: Session) -> None:
    if settings.auto_seed and not db.scalar(select(func.count(User.id))):
        log.info("empty database and AUTO_SEED=true: loading the demo hospital")
        await load_demo(db)
