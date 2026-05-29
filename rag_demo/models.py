from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class KnowledgeBaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{2,64}$")
    name: str
    allowed_skills: list[str] = Field(default_factory=lambda: ["answer_question"])
    description: str = ""
    tenant_id: str = "default"
    permission_tags: list[str] = Field(default_factory=list)


class KnowledgeBase(KnowledgeBaseCreate):
    created_at: str = Field(default_factory=utc_now)


class AccessContext(BaseModel):
    user_id: str = "demo-user"
    tenant_id: str = "default"
    permission_tags: list[str] = Field(default_factory=list)


class ApiRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DocumentIn(BaseModel):
    title: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    permission_tags: list[str] = Field(default_factory=list)
    access: AccessContext = Field(default_factory=AccessContext)


class DocumentCreateRequest(ApiRequest):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)
    permission_tags: list[str] = Field(default_factory=list)

    def to_document_in(self) -> DocumentIn:
        return DocumentIn(**self.model_dump())


class Document(BaseModel):
    id: str = Field(default_factory=lambda: f"doc_{uuid4().hex}")
    knowledge_base_id: str
    title: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    permission_tags: list[str] = Field(default_factory=list)
    status: str = "indexed"
    error: str = ""
    created_at: str = Field(default_factory=utc_now)


class Chunk(BaseModel):
    id: str = Field(default_factory=lambda: f"chunk_{uuid4().hex}")
    knowledge_base_id: str
    document_id: str
    title: str
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    tenant_id: str = "default"
    permission_tags: list[str] = Field(default_factory=list)
    embedding: list[float]
    created_at: str = Field(default_factory=utc_now)


class Source(BaseModel):
    knowledge_base_id: str
    document_id: str
    chunk_id: str
    title: str
    score: float
    vector_score: float = 0.0
    lexical_score: float = 0.0
    tenant_id: str = "default"
    permission_tags: list[str] = Field(default_factory=list)
    text: str


class QueryRequest(ApiRequest):
    question: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)


class QueryResponse(BaseModel):
    answer: str
    sources: list[Source]
    trace_id: str = Field(default_factory=lambda: f"trace_{uuid4().hex}")


class SkillRequest(ApiRequest):
    instruction: str = Field(min_length=1, max_length=4000)
    top_k: int = Field(default=5, ge=1, le=20)


class GeneratedArtifact(BaseModel):
    id: str
    filename: str
    media_type: str
    download_url: str
    instruction: str = ""


class SkillResponse(QueryResponse):
    skill: str
    artifact: GeneratedArtifact | None = None


class DocumentSummary(BaseModel):
    id: str
    knowledge_base_id: str
    title: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    permission_tags: list[str] = Field(default_factory=list)
    status: str = "indexed"
    error: str = ""
    chunk_count: int = 0
    created_at: str


class ReindexResponse(BaseModel):
    document_id: str
    chunk_count: int


class ArtifactRecord(BaseModel):
    id: str = Field(default_factory=lambda: f"artifact_{uuid4().hex}")
    knowledge_base_id: str
    user_id: str = "demo-user"
    tenant_id: str = "default"
    filename: str
    media_type: str
    skill: str
    instruction: str = ""
    permission_tags: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=utc_now)


class ArtifactSummary(BaseModel):
    id: str
    knowledge_base_id: str
    user_id: str
    filename: str
    media_type: str
    skill: str
    instruction: str = ""
    permission_tags: list[str] = Field(default_factory=list)
    download_url: str
    created_at: str


class ArtifactPreview(BaseModel):
    id: str
    filename: str
    media_type: str
    skill: str
    instruction: str = ""
    content: str


class RuntimeConfig(BaseModel):
    auth_mode: str
    vector_store: str
    vector_store_uri: str
    vector_store_collection: str
    llm_provider: str
    llm_model: str
    llm_ready: bool
    embedding_provider: str
    embedding_model: str
    embedding_ready: bool
