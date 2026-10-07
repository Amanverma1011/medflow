"""Centralised, environment-driven configuration. Nothing else reads os.environ."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

REPO_ROOT = Path(__file__).resolve().parents[3]
INSECURE_SECRET = "change-me-in-production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(REPO_ROOT / ".env", ".env"), extra="ignore")

    app_env: str = "development"
    hospital_name: str = "MedFlow General Hospital"
    hospital_tz: str = "UTC"

    database_url: str = "postgresql+psycopg://medflow:medflow@localhost:5433/medflow"
    # Read-only role used by the Operations Copilot. Derived from database_url when blank.
    analytics_database_url: str = ""
    analytics_db_user: str = "medflow_ro"
    analytics_db_password: str = "medflow_ro"

    jwt_secret: str = INSECURE_SECRET
    access_token_minutes: int = 30
    refresh_token_days: int = 7
    cookie_secure: bool = False
    cors_origins: str = "http://localhost:5174,http://localhost:8080"

    # AI providers. Blank API key => deterministic local fallback (clearly labelled demo mode).
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = ""
    embedding_base_url: str = "https://api.openai.com/v1"
    embedding_api_key: str = ""
    embedding_model: str = ""
    vector_dimension: int = 384
    reranker: str = "lexical"

    rag_alpha: float = 0.6  # weight of semantic similarity in the hybrid score
    rag_beta: float = 0.4  # weight of keyword score
    rag_top_k: int = 20  # candidates fetched before reranking
    rag_final_k: int = 5  # chunks placed in the LLM context
    rag_min_confidence: float = 0.42  # below this we refuse to answer from context
    rag_chunk_chars: int = 900
    rag_chunk_overlap: int = 150

    data_dir: Path = REPO_ROOT / "data"
    max_upload_mb: int = 10
    auto_seed: bool = False
    demo_password: str = "MedFlow#2026"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def readonly_url(self) -> str:
        if self.analytics_database_url:
            return self.analytics_database_url
        url = make_url(self.database_url).set(username=self.analytics_db_user, password=self.analytics_db_password)
        return url.render_as_string(hide_password=False)

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_api_key and self.llm_model)

    @property
    def remote_embeddings(self) -> bool:
        return bool(self.embedding_api_key and self.embedding_model)


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if s.app_env == "production" and s.jwt_secret == INSECURE_SECRET:
        raise RuntimeError("JWT_SECRET must be set in production")
    return s


settings = get_settings()
