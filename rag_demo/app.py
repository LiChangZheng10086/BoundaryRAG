from __future__ import annotations

from functools import lru_cache

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from rag_demo.auth import AuthConfigError, AuthError, decode_access_token
from rag_demo.config import get_settings
from rag_demo.document_parsers import UploadSecurityPolicy
from rag_demo.embeddings import create_embedding_provider
from rag_demo.llm import create_llm_provider
from rag_demo.models import (
    AccessContext,
    ArtifactPreview,
    ArtifactSummary,
    Document,
    DocumentCreateRequest,
    DocumentSummary,
    KnowledgeBase,
    KnowledgeBaseCreate,
    OperationEvent,
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


app = FastAPI(title="RAG Demo", version="0.1.0")
app.mount("/static", StaticFiles(directory="rag_demo/web"), name="static")


def parse_tag_string(value: str) -> list[str]:
    return [tag.strip() for tag in value.split(",") if tag.strip()]


def get_access_context(
    authorization: str | None = Header(default=None),
    x_user_id: str = Header(default="demo-user"),
    x_tenant_id: str = Header(default="default"),
    x_permission_tags: str = Header(default=""),
) -> AccessContext:
    settings = get_settings()
    if settings.auth_mode not in {"demo", "jwt"}:
        raise HTTPException(status_code=500, detail=f"unsupported RAG_AUTH_MODE '{settings.auth_mode}'")

    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise HTTPException(status_code=401, detail="Authorization header must be a Bearer token")
        try:
            return decode_access_token(token, settings)
        except AuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        except AuthConfigError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    if settings.auth_mode == "jwt":
        raise HTTPException(status_code=401, detail="missing Bearer token")

    return AccessContext(
        user_id=x_user_id or "demo-user",
        tenant_id=x_tenant_id or "default",
        permission_tags=parse_tag_string(x_permission_tags),
    )


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
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/runtime-config", response_model=RuntimeConfig)
async def runtime_config() -> RuntimeConfig:
    settings = get_settings()
    return RuntimeConfig(
        auth_mode=settings.auth_mode,
        metadata_store="sqlite",
        metadata_store_uri=str(settings.sqlite_path),
        vector_store="milvus-lite",
        vector_store_uri=str(settings.milvus_uri),
        vector_store_collection=settings.milvus_collection,
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
        return await service.query(kb_id=kb_id, question=payload.question, top_k=payload.top_k, access=access)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


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
