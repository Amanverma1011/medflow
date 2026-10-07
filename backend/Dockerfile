# Build context is the repository root (see docker-compose.yml) so scripts/ and data/ are included.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app/backend

COPY backend/requirements.txt .
RUN pip install -r requirements.txt

COPY backend/ /app/backend/
COPY scripts/ /app/scripts/
COPY data/documents/ /app/data/documents/
COPY data/sample/ /app/data/sample/

# Run as an unprivileged user; only the uploads folder is writable.
RUN useradd --create-home --uid 10001 medflow \
    && mkdir -p /app/data/uploads && chown -R medflow /app/data/uploads
USER medflow

EXPOSE 8000
# Migrate, then serve. The demo hospital is seeded on first start when AUTO_SEED=true.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'"]
