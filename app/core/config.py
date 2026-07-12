from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central app configuration, loaded from environment variables / .env."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Legal Contract RAG Analyzer"
    log_level: str = "INFO"

    database_url: str = "sqlite:///./legal_rag.db"

    upload_dir: str = "./data/uploads"
    chroma_persist_dir: str = "./data/chroma"
    max_file_size_mb: int = 20
    allowed_extensions: list[str] = [".pdf", ".docx", ".txt"]

    llm_provider: str = "stub"  # "stub" | "groq" | "gemini" | "openai" (swappable, see app/services/llm_service.py)
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"


@lru_cache
def get_settings() -> Settings:
    return Settings()
