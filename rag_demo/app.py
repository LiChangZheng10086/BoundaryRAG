from __future__ import annotations

from contextlib import asynccontextmanager
from functools import lru_cache

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from rag_demo.auth import (
    AuthConfigError,
    AuthError,
    access_from_claims,
    decode_access_token_payload,
    token_cache_id,
    token_expires_in_seconds,
)
from rag_demo.cache import RedisCache, RedisUnavailableError, create_redis_cache
from rag_demo.config import get_settings
from rag_demo.document_parsers import UploadSecurityPolicy
from rag_demo.embeddings import create_embedding_provider
from rag_demo.llm import create_llm_provider
from rag_demo.models import (
    AccessContext,
    ArtifactPreview,
    ArtifactSummary,
    Conversation,
    ConversationMessage,
    Document,
    DocumentCreateRequest,
    DocumentSummary,
    KnowledgeBase,
    KnowledgeBaseCreate,
    OperationEvent,
    LogoutResponse,
    QueryRequest,
    QueryResponse,
    ReindexResponse,
    RuntimeConfig,
    SkillRequest,
    SkillResponse,
)
from rag_demo.service import RagService
from rag_demo.store import SqliteStore
from rag_demo.vector_store import create_chunk_store


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        yield
    finally:
        await get_redis_cache().close()


app = FastAPI(title="RAG Demo", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="rag_demo/web"), name="static")


def parse_tag_string(value: str) -> list[str]:
    return [tag.strip() for tag in value.split(",") if tag.strip()]


@lru_cache
def get_redis_cache() -> RedisCache:
    return create_redis_cache(get_settings())


async def get_access_context(
    authorization: str | None = Header(default=None),
    x_user_id: str = Header(default="demo-user"),
    x_tenant_id: str = Header(default="default"),
    x_permission_tags: str = Header(default=""),
    cache: RedisCache = Depends(get_redis_cache),
) -> AccessContext:
    settings = get_settings()
    if settings.auth_mode not in {"demo", "jwt"}:
        raise HTTPException(status_code=500, detail=f"unsupported RAG_AUTH_MODE '{settings.auth_mode}'")

    if authorization:
        token = require_bearer_token(authorization)
        try:
            payload = decode_access_token_payload(token, settings)
            if await cache.is_jwt_revoked(token_cache_id(token, payload)):
                raise HTTPException(status_code=401, detail="JWT token has been revoked")
            return access_from_claims(payload)
        except AuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        except AuthConfigError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        except RedisUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    if settings.auth_mode == "jwt":
        raise HTTPException(status_code=401, detail="missing Bearer token")

    return AccessContext(
        user_id=x_user_id or "demo-user",
        tenant_id=x_tenant_id or "default",
        permission_tags=parse_tag_string(x_permission_tags),
    )


def require_bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="missing Bearer token")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Authorization header must be a Bearer token")
    return token


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse("rag_demo/web/index.html")


@lru_cache
def get_service() -> RagService:
    settings = get_settings()
    store = SqliteStore(settings.sqlite_path, legacy_data_dir=settings.data_dir)
    chunk_store = create_chunk_store(uri=settings.milvus_uri, collection_name=settings.milvus_collection)
    legacy_chunks = store.read_legacy_chunks()
    if legacy_chunks:
        chunk_store.upsert_chunks(legacy_chunks)
        store.mark_legacy_chunks_migrated()
    embeddings = create_embedding_provider(settings)
    llm = create_llm_provider(settings)
    return RagService(
        store=store,
        chunk_store=chunk_store,
        embeddings=embeddings,
        llm=llm,
        artifact_dir=settings.artifact_dir,
        max_document_chars=settings.max_document_chars,
        upload_parse_timeout_seconds=settings.upload_parse_timeout_seconds,
        upload_security_policy=UploadSecurityPolicy(
            max_archive_members=settings.max_archive_members,
            max_archive_uncompressed_bytes=settings.max_archive_uncompressed_bytes,
            max_archive_compression_ratio=settings.max_archive_compression_ratio,
        ),
    )


@app.get("/health")
async def health(cache: RedisCache = Depends(get_redis_cache)) -> dict[str, str]:
    redis_status = await cache.status()
    redis_value = "disabled"
    if redis_status.enabled:
        redis_value = "ok" if redis_status.ready else "unavailable"
    return {"status": "ok", "redis": redis_value}


@app.get("/runtime-config", response_model=RuntimeConfig)
async def runtime_config(cache: RedisCache = Depends(get_redis_cache)) -> RuntimeConfig:
    settings = get_settings()
    redis_status = await cache.status()
    return RuntimeConfig(
        auth_mode=settings.auth_mode,
        metadata_store="sqlite",
        metadata_store_uri=str(settings.sqlite_path),
        vector_store="milvus-lite",
        vector_store_uri=str(settings.milvus_uri),
        vector_store_collection=settings.milvus_collection,
        cache_store="redis" if redis_status.enabled else "disabled",
        cache_store_uri=redis_status.url,
        cache_ready=redis_status.ready,
        llm_provider=settings.llm_provider,
        llm_model=settings.deepseek_model if settings.llm_provider == "deepseek" else "local-boundary",
        llm_ready=settings.llm_provider != "deepseek" or bool(settings.deepseek_api_key),
        embedding_provider=settings.embedding_provider,
        embedding_model=(
            settings.dashscope_embedding_model
            if settings.embedding_provider == "dashscope"
            else "local-hash"
        ),
        embedding_ready=settings.embedding_provider != "dashscope" or bool(settings.dashscope_api_key),
    )


@app.post("/auth/logout", response_model=LogoutResponse)
async def logout(
    authorization: str | None = Header(default=None),
    cache: RedisCache = Depends(get_redis_cache),
) -> LogoutResponse:
    settings = get_settings()
    token = require_bearer_token(authorization)
    try:
        payload = decode_access_token_payload(token, settings)
        token_id = token_cache_id(token, payload)
        ttl_seconds = token_expires_in_seconds(payload)
        await cache.revoke_jwt(token_id, ttl_seconds=ttl_seconds)
        return LogoutResponse(
            revoked=True,
            token_id=token_id,
            expires_at=int(payload.get("exp") or 0),
        )
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except AuthConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except RedisUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/knowledge-bases", response_model=KnowledgeBase)
async def create_knowledge_base(
    payload: KnowledgeBaseCreate,
    access: AccessContext = Depends(get_access_context),
    service: RagService = Depends(get_service),
) -> KnowledgeBase:
    try:
        return service.create_knowledge_base(payload, access=access)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.get("/knowledge-bases", response_model=list[KnowledgeBase])
async def list_knowledge_bases(
    access: AccessContext = Depends(get_access_context),
    service: RagService = Depends(get_service),
) -> list[KnowledgeBase]:
    return service.list_knowledge_bases(access=access)


@app.delete("/knowledge-bases/{kb_id}", status_code=204)
async def delete_knowledge_base(
    kb_id: str,
    access: AccessContext = Depends(get_access_context),
    service: RagService = Depends(get_service),
) -> None:
    try:
        service.delete_knowledge_base(kb_id=kb_id, access=access)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/knowledge-bases/{kb_id}/documents", response_model=Document)
async def add_document(
    kb_id: str,
    payload: DocumentCreateRequest,
    access: AccessContext = Depends(get_access_context),
    service: RagService = Depends(get_service),
) -> Document:
    try:
        return await service.add_document(kb_id=kb_id, data=payload.to_document_in(), access=access)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/knowledge-bases/{kb_id}/documents/upload", response_model=Document)
async def upload_document(
    kb_id: str,
    file: UploadFile = File(...),
    permission_tags: str = Form(default=""),
    access: AccessContext = Depends(get_access_context),
    service: RagService = Depends(get_service),
) -> Document:
    try:
        settings = get_settings()
        chunks: list[bytes] = []
        total_size = 0
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            total_size += len(chunk)
            if total_size > settings.max_upload_bytes:
                raise HTTPException(status_code=413, detail="uploaded file is too large")
            chunks.append(chunk)
        data = b"".join(chunks)
        return await service.add_uploaded_document(
            kb_id=kb_id,
            filename=file.filename or "uploaded-document",
            content_type=file.content_type,
            data=data,
            permission_tags=parse_tag_string(permission_tags),
            access=access,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/knowledge-bases/{kb_id}/documents", response_model=list[DocumentSummary])
async def list_documents(
    kb_id: str,
    access: AccessContext = Depends(get_access_context),
    service: RagService = Depends(get_service),
) -> list[DocumentSummary]:
    try:
        return service.list_documents(kb_id=kb_id, access=access)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/knowledge-bases/{kb_id}/documents/{document_id}", response_model=Document)
async def get_document(
    kb_id: str,
    document_id: str,
    access: AccessContext = Depends(get_access_context),
    service: RagService = Depends(get_service),
) -> Document:
    try:
        return service.get_document(kb_id=kb_id, document_id=document_id, access=access)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/knowledge-bases/{kb_id}/conversations", response_model=list[Conversation])
async def list_conversations(
    kb_id: str,
    access: AccessContext = Depends(get_access_context),
    service: RagService = Depends(get_service),
) -> list[Conversation]:
    try:
        return service.list_conversations(kb_id=kb_id, access=access)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.get("/knowledge-bases/{kb_id}/conversations/{conversation_id}/messages", response_model=list[ConversationMessage])
async def list_conversation_messages(
    kb_id: str,
    conversation_id: str,
    access: AccessContext = Depends(get_access_context),
    service: RagService = Depends(get_service),
) -> list[ConversationMessage]:
    try:
        return service.list_conversation_messages(kb_id=kb_id, conversation_id=conversation_id, access=access)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.delete("/knowledge-bases/{kb_id}/documents/{document_id}", status_code=204)
async def delete_document(
    kb_id: str,
    document_id: str,
    access: AccessContext = Depends(get_access_context),
    service: RagService = Depends(get_service),
) -> None:
    try:
        service.delete_document(kb_id=kb_id, document_id=document_id, access=access)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/knowledge-bases/{kb_id}/documents/{document_id}/reindex", response_model=ReindexResponse)
async def reindex_document(
    kb_id: str,
    document_id: str,
    access: AccessContext = Depends(get_access_context),
    service: RagService = Depends(get_service),
) -> ReindexResponse:
    try:
        return await service.reindex_document(
            kb_id=kb_id,
            document_id=document_id,
            access=access,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/knowledge-bases/{kb_id}/query", response_model=QueryResponse)
async def query(
    kb_id: str,
    payload: QueryRequest,
    access: AccessContext = Depends(get_access_context),
    service: RagService = Depends(get_service),
) -> QueryResponse:
    try:
        return await service.query(
            kb_id=kb_id,
            question=payload.question,
            top_k=payload.top_k,
            conversation_id=payload.conversation_id,
            access=access,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/knowledge-bases/{kb_id}/query/stream")
async def query_stream(
    kb_id: str,
    payload: QueryRequest,
    access: AccessContext = Depends(get_access_context),
    service: RagService = Depends(get_service),
) -> StreamingResponse:
    try:
        chunks = await service.query_stream(
            kb_id=kb_id,
            question=payload.question,
            top_k=payload.top_k,
            conversation_id=payload.conversation_id,
            access=access,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    async def stream_body():
        try:
            async for chunk in chunks:
                if chunk:
                    yield chunk
        except Exception as exc:
            message = str(exc).strip() or exc.__class__.__name__
            yield f"\n\n[生成中断：{message[:200]}]"

    conversation_id = getattr(chunks, "conversation_id", payload.conversation_id or "")
    headers = {"X-Conversation-Id": conversation_id} if conversation_id else None
    return StreamingResponse(stream_body(), media_type="text/plain; charset=utf-8", headers=headers)


@app.post("/knowledge-bases/{kb_id}/skills/{skill_name}", response_model=SkillResponse)
async def run_skill(
    kb_id: str,
    skill_name: str,
    payload: SkillRequest,
    access: AccessContext = Depends(get_access_context),
    service: RagService = Depends(get_service),
) -> SkillResponse:
    try:
        return await service.run_skill(
            kb_id=kb_id,
            skill_name=skill_name,
            instruction=payload.instruction,
            top_k=payload.top_k,
            access=access,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/knowledge-bases/{kb_id}/artifacts/{artifact_id}/download", include_in_schema=False)
async def download_artifact(
    kb_id: str,
    artifact_id: str,
    access: AccessContext = Depends(get_access_context),
    service: RagService = Depends(get_service),
) -> FileResponse:
    try:
        artifact, path = service.get_artifact_file(
            kb_id=kb_id,
            artifact_id=artifact_id,
            access=access,
        )
        return FileResponse(path, filename=artifact.filename, media_type=artifact.media_type)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.get("/knowledge-bases/{kb_id}/artifacts/{artifact_id}/preview", response_model=ArtifactPreview)
async def preview_artifact(
    kb_id: str,
    artifact_id: str,
    access: AccessContext = Depends(get_access_context),
    service: RagService = Depends(get_service),
) -> ArtifactPreview:
    try:
        return service.preview_artifact(kb_id=kb_id, artifact_id=artifact_id, access=access)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.delete("/knowledge-bases/{kb_id}/artifacts/{artifact_id}", status_code=204)
async def delete_artifact(
    kb_id: str,
    artifact_id: str,
    access: AccessContext = Depends(get_access_context),
    service: RagService = Depends(get_service),
) -> None:
    try:
        service.delete_artifact(kb_id=kb_id, artifact_id=artifact_id, access=access)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.get("/knowledge-bases/{kb_id}/artifacts", response_model=list[ArtifactSummary])
async def list_artifacts(
    kb_id: str,
    access: AccessContext = Depends(get_access_context),
    service: RagService = Depends(get_service),
) -> list[ArtifactSummary]:
    try:
        return service.list_artifacts(kb_id=kb_id, access=access)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.get("/operation-events", response_model=list[OperationEvent])
async def list_operation_events(
    limit: int = 50,
    kb_id: str | None = None,
    access: AccessContext = Depends(get_access_context),
    service: RagService = Depends(get_service),
) -> list[OperationEvent]:
    try:
        return service.list_operation_events(access=access, kb_id=kb_id, limit=limit)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
