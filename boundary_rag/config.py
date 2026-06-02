"""后端基于环境变量的配置。

Settings 是不可变 dataclass，每个 FastAPI 依赖都可以从 `.env` 和环境变量
构建一份清晰的配置快照。密钥只从这里读取，绝不硬编码进源码。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class Settings:
    """按存储、认证、Embedding 和 LLM provider 分组的运行配置。"""

    data_dir: Path = field(default_factory=lambda: Path(os.getenv("RAG_DATA_DIR", ".rag_data")))
    artifact_dir: Path = field(default_factory=lambda: Path(os.getenv("RAG_ARTIFACT_DIR", ".rag_data/artifacts")))
    sqlite_path: Path = field(default_factory=lambda: Path(os.getenv("RAG_SQLITE_PATH", ".rag_data/boundaryrag.sqlite3")))
    milvus_uri: Path = field(default_factory=lambda: Path(os.getenv("RAG_MILVUS_URI", ".rag_data/milvus_lite.db")))
    milvus_collection: str = field(default_factory=lambda: os.getenv("RAG_MILVUS_COLLECTION", "boundaryrag_chunks"))
    max_upload_bytes: int = field(default_factory=lambda: int(os.getenv("RAG_MAX_UPLOAD_MB", "25")) * 1024 * 1024)
    upload_parse_timeout_seconds: float = field(
        default_factory=lambda: float(os.getenv("RAG_UPLOAD_PARSE_TIMEOUT_SECONDS", "10"))
    )
    max_archive_members: int = field(default_factory=lambda: int(os.getenv("RAG_MAX_ARCHIVE_MEMBERS", "512")))
    max_archive_uncompressed_bytes: int = field(
        default_factory=lambda: int(os.getenv("RAG_MAX_ARCHIVE_UNCOMPRESSED_MB", "100")) * 1024 * 1024
    )
    max_archive_compression_ratio: float = field(
        default_factory=lambda: float(os.getenv("RAG_MAX_ARCHIVE_COMPRESSION_RATIO", "100"))
    )
    max_document_chars: int = field(default_factory=lambda: int(os.getenv("RAG_MAX_DOCUMENT_CHARS", "200000")))
    auth_mode: str = field(default_factory=lambda: os.getenv("RAG_AUTH_MODE", "demo").strip().lower())
    jwt_secret: str | None = field(default_factory=lambda: os.getenv("RAG_JWT_SECRET"))
    jwt_issuer: str | None = field(default_factory=lambda: os.getenv("RAG_JWT_ISSUER"))
    jwt_audience: str | None = field(default_factory=lambda: os.getenv("RAG_JWT_AUDIENCE"))
    jwt_leeway_seconds: int = field(default_factory=lambda: int(os.getenv("RAG_JWT_LEEWAY_SECONDS", "30")))
    redis_enabled: bool = field(default_factory=lambda: _env_bool("RAG_REDIS_ENABLED", True))
    redis_url: str = field(default_factory=lambda: os.getenv("RAG_REDIS_URL", "redis://localhost:6379/0"))
    redis_key_prefix: str = field(default_factory=lambda: os.getenv("RAG_REDIS_KEY_PREFIX", "boundaryrag"))
    redis_timeout_seconds: float = field(default_factory=lambda: float(os.getenv("RAG_REDIS_TIMEOUT_SECONDS", "1")))
    redis_default_ttl_seconds: int = field(default_factory=lambda: int(os.getenv("RAG_REDIS_DEFAULT_TTL_SECONDS", "86400")))
    auth_session_ttl_seconds: int = field(default_factory=lambda: int(os.getenv("RAG_AUTH_SESSION_TTL_SECONDS", "86400")))
    embedding_provider: str = field(default_factory=lambda: os.getenv("EMBEDDING_PROVIDER", "local"))
    dashscope_api_key: str | None = field(default_factory=lambda: os.getenv("DASHSCOPE_API_KEY"))
    dashscope_embedding_model: str = field(
        default_factory=lambda: os.getenv(
            "DASHSCOPE_EMBEDDING_MODEL",
            "tongyi-embedding-vision-flash-2026-03-06",
        )
    )
    dashscope_embedding_batch_size: int = field(
        default_factory=lambda: int(os.getenv("DASHSCOPE_EMBEDDING_BATCH_SIZE", "20"))
    )
    llm_provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "local"))
    deepseek_api_key: str | None = field(default_factory=lambda: os.getenv("DEEPSEEK_API_KEY"))
    deepseek_model: str = field(default_factory=lambda: os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro"))
    deepseek_base_url: str = field(default_factory=lambda: os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))


def _env_bool(name: str, default: bool) -> bool:
    """解析 `.env` 文件里常见的布尔真值字符串。"""
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def get_settings() -> Settings:
    """为依赖工厂和测试返回一份新的配置快照。"""
    return Settings()
