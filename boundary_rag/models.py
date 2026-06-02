"""API、服务层、存储层和测试共用的 Pydantic 模型。

这些模型定义了产品契约：知识库归属、用户访问、文档索引状态、检索来源、
对话、生成产物、操作事件和运行诊断。把 schema 集中在这里，可以避免路由
处理器和存储适配器各自发明不同的数据结构。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> str:
    """返回持久化记录使用的 ISO UTC 时间戳。"""
    return datetime.now(timezone.utc).isoformat()


class KnowledgeBaseCreate(BaseModel):
    """创建隔离知识库时的客户端输入。"""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{2,64}$")
    name: str
    allowed_skills: list[str] = Field(default_factory=lambda: ["answer_question"])
    description: str = ""
    tenant_id: str = "default"
    permission_tags: list[str] = Field(default_factory=list)


class KnowledgeBase(KnowledgeBaseCreate):
    """带归属用户和创建时间的持久化知识库。"""

    owner_user_id: str = ""
    created_at: str = Field(default_factory=utc_now)


class AccessContext(BaseModel):
    """从会话、JWT 或演示请求头解析出的授权上下文。"""

    user_id: str = "demo-user"
    username: str = ""
    role: str = "user"
    tenant_id: str = "default"
    permission_tags: list[str] = Field(default_factory=list)


class ApiRequest(BaseModel):
    """拒绝多余字段的请求基类。"""

    model_config = ConfigDict(extra="forbid")


class DocumentIn(BaseModel):
    """上传解析或直接 API 创建后进入服务层的文档输入。"""

    title: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    permission_tags: list[str] = Field(default_factory=list)
    access: AccessContext = Field(default_factory=AccessContext)


class DocumentCreateRequest(ApiRequest):
    """直接创建文本类文档的 API 请求体。"""

    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)
    permission_tags: list[str] = Field(default_factory=list)

    def to_document_in(self) -> DocumentIn:
        """把 API 输入转换为服务层文档结构。"""
        return DocumentIn(**self.model_dump())


class Document(BaseModel):
    """切分前持久化的文档 metadata 和全文。"""

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
    """存入 Milvus Lite、可向量检索的 child chunk。"""

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
    """返回给生成层和可选 API 消费方的检索命中 chunk。"""

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
    """问答请求，可携带 conversation_id 延续上下文。"""

    question: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)
    conversation_id: str | None = Field(default=None, pattern=r"^conv_[a-f0-9]{32}$")


class QueryResponse(BaseModel):
    """答案响应，包含 trace 和 conversation 标识。"""

    answer: str
    sources: list[Source]
    trace_id: str = Field(default_factory=lambda: f"trace_{uuid4().hex}")
    conversation_id: str = ""


class Conversation(BaseModel):
    """某个知识库内按用户隔离的对话线程。"""

    id: str = Field(default_factory=lambda: f"conv_{uuid4().hex}")
    knowledge_base_id: str
    user_id: str = "demo-user"
    tenant_id: str = "default"
    title: str = "新对话"
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)


class ConversationMessage(BaseModel):
    """持久化保存、用于上下文回放的一条用户或助手消息。"""

    id: str = Field(default_factory=lambda: f"msg_{uuid4().hex}")
    conversation_id: str
    role: str = Field(pattern=r"^(user|assistant)$")
    content: str
    created_at: str = Field(default_factory=utc_now)


class SkillRequest(ApiRequest):
    """写文档和生成产物类 skills 的请求体。"""

    instruction: str = Field(min_length=1, max_length=4000)
    top_k: int = Field(default=5, ge=1, le=20)


class GeneratedArtifact(BaseModel):
    """由 skill 生成的可下载产物。"""

    id: str
    filename: str
    media_type: str
    download_url: str
    instruction: str = ""


class SkillResponse(QueryResponse):
    """技能执行结果，可能包含生成产物。"""

    skill: str
    artifact: GeneratedArtifact | None = None


class DocumentSummary(BaseModel):
    """文档列表 UI 使用的轻量文档行。"""

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
    """重建单个文档 chunk 后返回的结果。"""

    document_id: str
    chunk_count: int


class ArtifactRecord(BaseModel):
    """存入 SQLite 的产物 metadata。"""

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
    """带可直接使用下载 URL 的产物列表项。"""

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
    """从生成产物文件中提取的文本预览。"""

    id: str
    filename: str
    media_type: str
    skill: str
    instruction: str = ""
    content: str


class OperationEvent(BaseModel):
    """记录用户动作和存储迁移的审计式事件。"""

    id: str = Field(default_factory=lambda: f"op_{uuid4().hex}")
    event_type: str
    user_id: str = "system"
    tenant_id: str = "default"
    knowledge_base_id: str = ""
    document_id: str = ""
    artifact_id: str = ""
    message: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now)


class RuntimeConfig(BaseModel):
    """展示在设置页中的运行诊断信息。"""

    auth_mode: str
    user_store: str = "sqlite"
    session_store: str
    session_ttl_seconds: int
    metadata_store: str
    metadata_store_uri: str
    vector_store: str
    vector_store_uri: str
    vector_store_collection: str
    cache_store: str
    cache_store_uri: str
    cache_ready: bool
    llm_provider: str
    llm_model: str
    llm_ready: bool
    embedding_provider: str
    embedding_model: str
    embedding_ready: bool


class LogoutResponse(BaseModel):
    """删除会话或撤销 JWT 后的退出登录响应。"""

    revoked: bool
    token_id: str = ""
    expires_at: int = 0


class UserAccount(BaseModel):
    """由 SQLite 支撑的登录账号。"""

    username: str = Field(pattern=r"^[a-zA-Z0-9_-]{2,64}$")
    password_hash: str
    role: str = Field(pattern=r"^(admin|user)$")
    tenant_id: str = "default"
    permission_tags: list[str] = Field(default_factory=list)
    active: bool = True
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)


class LoginRequest(ApiRequest):
    """用户名/密码登录请求体。"""

    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class LoginUser(BaseModel):
    """登录成功后返回给前端的用户信息。"""

    username: str
    user_id: str
    role: str
    tenant_id: str
    permission_tags: list[str] = Field(default_factory=list)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_at: int
    expires_in: int
    user: LoginUser
