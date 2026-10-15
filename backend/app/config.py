from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database_url: str
    ollama_base_url: str
    chat_model: str
    embed_model: str
    embed_dimensions: int
    max_upload_bytes: int
    frontend_origin: str
    redis_url: str
    data_dir: Path
    ocr_enabled: bool
    min_relevance_score: float


def get_settings() -> Settings:
    return Settings(
        database_url=os.getenv(
            "DATABASE_URL", "postgresql://paperwise:paperwise@localhost:5432/paperwise"
        ),
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip(
            "/"
        ),
        chat_model=os.getenv("OLLAMA_CHAT_MODEL", "gemma3:4b"),
        embed_model=os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text"),
        embed_dimensions=int(os.getenv("OLLAMA_EMBED_DIMENSIONS", "768")),
        max_upload_bytes=int(os.getenv("MAX_UPLOAD_MB", "20")) * 1024 * 1024,
        frontend_origin=os.getenv("FRONTEND_ORIGIN", "http://localhost:3000"),
        redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        data_dir=Path(os.getenv("PAPERWISE_DATA_DIR", "./data")),
        ocr_enabled=os.getenv("PAPERWISE_ENABLE_OCR", "false").lower()
        in {"1", "true", "yes"},
        min_relevance_score=float(os.getenv("MIN_RELEVANCE_SCORE", "0.28")),
    )
