from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

from rag_demo.chunking import chunk_document
from rag_demo.embeddings import EmbeddingProvider
from rag_demo.llm import LLMProvider
from rag_demo.models import (
    AccessContext,
    ArtifactRecord,
    ArtifactPreview,
    ArtifactSummary,
    Conversation,
    ConversationMessage,
    Chunk,
    Document,
    DocumentIn,
    DocumentSummary,
    KnowledgeBase,
    KnowledgeBaseCreate,
    OperationEvent,
    QueryResponse,
    ReindexResponse,
    SkillResponse,
)
from rag_demo.retriever import Retriever
from rag_demo.skills import SkillRegistry
from rag_demo.store import JsonStore, SqliteStore
from rag_demo.vector_store import ChunkStore, create_chunk_store

from rag_demo.document_parsers import UploadSecurityPolicy, parse_uploaded_document


DEFAULT_MAX_DOCUMENT_CHARS = 200_000
CONVERSATION_CONTEXT_MESSAGES = 12


@dataclass(frozen=True)
class ConversationStream:
    conversation_id: str
    chunks: AsyncIterator[str]

    def __aiter__(self) -> AsyncIterator[str]:
        return self.chunks


class RagService:
    def __init__(
        self,
        *,
        store: JsonStore | SqliteStore,
        chunk_store: ChunkStore | None = None,
        embeddings: EmbeddingProvider,
        llm: LLMProvider,
        artifact_dir: Path,
        max_document_chars: int = DEFAULT_MAX_DOCUMENT_CHARS,
        upload_parse_timeout_seconds: float = 10.0,
        upload_security_policy: UploadSecurityPolicy | None = None,
    ) -> None:
        if max_document_chars < 1:
            raise ValueError("max_document_chars must be greater than 0")
        if upload_parse_timeout_seconds <= 0:
            raise ValueError("upload_parse_timeout_seconds must be greater than 0")
        self.store = store
        self.embeddings = embeddings
        self.llm = llm
        self.artifact_dir = artifact_dir
        self.max_document_chars = max_document_chars
        self.upload_parse_timeout_seconds = upload_parse_timeout_seconds
        self.upload_security_policy = upload_security_policy or UploadSecurityPolicy()
        self.chunk_store = chunk_store or create_chunk_store(
            uri=store.data_dir / "milvus_lite.db",
            collection_name="boundaryrag_chunks",
        )
        self.retriever = Retriever(self.chunk_store, embeddings)
        self.skills = SkillRegistry(artifact_dir)

    def create_knowledge_base(self, data: KnowledgeBaseCreate, access: AccessContext | None = None) -> KnowledgeBase:
        if access:
            if data.tenant_id != access.tenant_id:
                raise PermissionError(f"cannot create knowledge base in tenant '{data.tenant_id}'")
            self._require_tags(data.permission_tags, access=access, subject=f"knowledge base '{data.id}'")
        kb = KnowledgeBase(**data.model_dump())
        return self.store.create_knowledge_base(kb, user_id=access.user_id if access else "system")

    def list_knowledge_bases(self, access: AccessContext | None = None) -> list[KnowledgeBase]:
        items = self.store.list_knowledge_bases()
        if not access:
            return items
        return [
            kb
            for kb in items
            if kb.tenant_id == access.tenant_id
            and (not kb.permission_tags or set(kb.permission_tags).issubset(set(access.permission_tags)))
        ]

    def delete_knowledge_base(self, *, kb_id: str, access: AccessContext | None = None) -> None:
        access = access or AccessContext()
        kb = self._require_kb(kb_id, access=access)
        artifacts = self.store.list_artifacts(kb_id=kb.id, permission_tags=None)
        deleted = self.store.delete_knowledge_base(kb.id, user_id=access.user_id)
        if not deleted:
            raise KeyError(f"knowledge base '{kb_id}' does not exist")
        self.chunk_store.delete_knowledge_base_chunks(kb_id=kb.id)
        for artifact in artifacts:
            path = self.artifact_dir / artifact.filename
            if path.exists():
                path.unlink()

    async def add_document(
        self,
        *,
        kb_id: str,
        data: DocumentIn,
        access: AccessContext | None = None,
    ) -> Document:
        access = access or data.access
        data = self._validate_document_input(data)
        self._require_kb(kb_id, access=access)
        self._require_tags(data.permission_tags, access=access, subject=f"document '{data.title}'")
        document = Document(
            knowledge_base_id=kb_id,
            status="indexing",
            error="",
            **data.model_dump(exclude={"access"}),
        )
        self.store.add_document(document, user_id=access.user_id)
        try:
            chunks = await self._build_chunks(document)
            self.chunk_store.replace_document_chunks(kb_id=kb_id, document_id=document.id, chunks=chunks)
            return self.store.update_document_status(
                kb_id=kb_id,
                document_id=document.id,
                status="indexed",
                user_id=access.user_id,
            )
        except Exception as exc:
            self.chunk_store.replace_document_chunks(kb_id=kb_id, document_id=document.id, chunks=[])
            self.store.update_document_status(
                kb_id=kb_id,
                document_id=document.id,
                status="failed",
                error=self._error_message(exc),
                user_id=access.user_id,
            )
            raise

    async def add_uploaded_document(
        self,
        *,
        kb_id: str,
        filename: str,
        content_type: str | None,
        data: bytes,
        permission_tags: list[str],
        access: AccessContext | None = None,
    ) -> Document:
        access = access or AccessContext()
        try:
            parsed = await asyncio.wait_for(
                asyncio.to_thread(
                    parse_uploaded_document,
                    filename=filename,
                    content_type=content_type,
                    data=data,
                    security_policy=self.upload_security_policy,
                ),
                timeout=self.upload_parse_timeout_seconds,
            )
        except TimeoutError as exc:
            raise ValueError("uploaded file parsing timed out") from exc
        return await self.add_document(
            kb_id=kb_id,
            data=DocumentIn(
                title=parsed.title,
                content=parsed.content,
                metadata=parsed.metadata,
                permission_tags=permission_tags,
                access=access,
            ),
        )

    def list_documents(self, *, kb_id: str, access: AccessContext | None = None) -> list[DocumentSummary]:
        access = access or AccessContext()
        self._require_kb(kb_id, access=access)
        chunk_counts = self.chunk_store.count_chunks_by_document(
            kb_id=kb_id,
            tenant_id=access.tenant_id,
            permission_tags=access.permission_tags,
        )
        return self.store.list_documents(
            kb_id=kb_id,
            permission_tags=access.permission_tags,
            chunk_counts=chunk_counts,
        )

    def list_conversations(self, *, kb_id: str, access: AccessContext | None = None) -> list[Conversation]:
        access = access or AccessContext()
        kb = self._require_kb(kb_id, access=access)
        return self.store.list_conversations(
            kb_id=kb.id,
            user_id=access.user_id,
            tenant_id=access.tenant_id,
        )

    def list_conversation_messages(
        self,
        *,
        kb_id: str,
        conversation_id: str,
        access: AccessContext | None = None,
    ) -> list[ConversationMessage]:
        access = access or AccessContext()
        kb = self._require_kb(kb_id, access=access)
        conversation = self._get_conversation_for_access(kb=kb, access=access, conversation_id=conversation_id)
        return self.store.list_conversation_messages(conversation_id=conversation.id, limit=100)

    def get_document(self, *, kb_id: str, document_id: str, access: AccessContext | None = None) -> Document:
        access = access or AccessContext()
        self._require_kb(kb_id, access=access)
        document = self.store.get_document(kb_id=kb_id, document_id=document_id)
        if not document:
            raise KeyError(f"document '{document_id}' does not exist")
        self._require_tags(document.permission_tags, access=access, subject=f"document '{document_id}'")
        return document

    def delete_document(self, *, kb_id: str, document_id: str, access: AccessContext | None = None) -> None:
        access = access or AccessContext()
        self._require_kb(kb_id, access=access)
        document = self.store.get_document(kb_id=kb_id, document_id=document_id)
        if not document:
            raise KeyError(f"document '{document_id}' does not exist")
        self._require_tags(document.permission_tags, access=access, subject=f"document '{document_id}'")
        deleted = self.store.delete_document(kb_id=kb_id, document_id=document_id, user_id=access.user_id)
        if not deleted:
            raise KeyError(f"document '{document_id}' does not exist")
        self.chunk_store.delete_document_chunks(kb_id=kb_id, document_id=document_id)

    async def reindex_document(
        self,
        *,
        kb_id: str,
        document_id: str,
        access: AccessContext | None = None,
    ) -> ReindexResponse:
        access = access or AccessContext()
        self._require_kb(kb_id, access=access)
        document = self.store.get_document(kb_id=kb_id, document_id=document_id)
        if not document:
            raise KeyError(f"document '{document_id}' does not exist")
        self._require_tags(document.permission_tags, access=access, subject=f"document '{document_id}'")
        self.store.update_document_status(
            kb_id=kb_id,
            document_id=document_id,
            status="indexing",
            user_id=access.user_id,
        )
        try:
            chunks = await self._build_chunks(document.model_copy(update={"status": "indexing", "error": ""}))
            self.chunk_store.replace_document_chunks(kb_id=kb_id, document_id=document_id, chunks=chunks)
            self.store.update_document_status(
                kb_id=kb_id,
                document_id=document_id,
                status="indexed",
                user_id=access.user_id,
            )
            return ReindexResponse(document_id=document.id, chunk_count=len(chunks))
        except Exception as exc:
            self.store.update_document_status(
                kb_id=kb_id,
                document_id=document_id,
                status="failed",
                error=self._error_message(exc),
                user_id=access.user_id,
            )
            raise

    async def _build_chunks(self, document: Document) -> list[Chunk]:
        pieces = chunk_document(document.content)
        if not pieces:
            raise ValueError("document content is empty after normalization")
        texts = [piece.text for piece in pieces]
        embeddings = await self.embeddings.embed(texts)
        if len(embeddings) != len(pieces):
            raise RuntimeError(
                "embedding provider returned "
                f"{len(embeddings)} vectors for {len(pieces)} text chunks"
            )
        self._validate_embeddings(embeddings)
        kb = self._require_kb(document.knowledge_base_id)
        return [
            Chunk(
                knowledge_base_id=document.knowledge_base_id,
                document_id=document.id,
                title=document.title,
                text=piece.text,
                metadata=document.metadata | piece.metadata,
                tenant_id=kb.tenant_id,
                permission_tags=document.permission_tags,
                embedding=embedding,
            )
            for piece, embedding in zip(pieces, embeddings)
        ]

    def _validate_document_input(self, data: DocumentIn) -> DocumentIn:
        title = data.title.strip()
        if not title:
            raise ValueError("document title is empty")
        if not data.content.strip():
            raise ValueError("document content is empty")
        if len(data.content) > self.max_document_chars:
            raise ValueError(
                "document content is too large; "
                f"limit is {self.max_document_chars} characters"
            )
        return data.model_copy(update={"title": title})

    def _validate_embeddings(self, embeddings: list[list[float]]) -> None:
        if not embeddings:
            raise RuntimeError("embedding provider returned no vectors")
        dimension = len(embeddings[0])
        if dimension == 0:
            raise RuntimeError("embedding provider returned empty vectors")
        if any(len(embedding) != dimension for embedding in embeddings):
            raise RuntimeError("embedding provider returned inconsistent vector dimensions")

    def _error_message(self, exc: Exception) -> str:
        message = str(exc).strip()
        return message[:500] if message else exc.__class__.__name__

    def _resolve_conversation(
        self,
        *,
        kb: KnowledgeBase,
        access: AccessContext,
        conversation_id: str | None,
        question: str,
    ) -> Conversation:
        if conversation_id:
            return self._get_conversation_for_access(kb=kb, access=access, conversation_id=conversation_id)

        return self.store.create_conversation(
            Conversation(
                knowledge_base_id=kb.id,
                user_id=access.user_id,
                tenant_id=access.tenant_id,
                title=self._conversation_title(question),
            )
        )

    def _get_conversation_for_access(
        self,
        *,
        kb: KnowledgeBase,
        access: AccessContext,
        conversation_id: str,
    ) -> Conversation:
        conversation = self.store.get_conversation(conversation_id)
        if not conversation:
            raise KeyError(f"conversation '{conversation_id}' does not exist")
        if conversation.knowledge_base_id != kb.id:
            raise PermissionError(f"conversation '{conversation_id}' is not in knowledge base '{kb.id}'")
        if conversation.user_id != access.user_id or conversation.tenant_id != access.tenant_id:
            raise PermissionError(f"conversation '{conversation_id}' is not accessible")
        return conversation

    def _record_conversation_turn(self, *, conversation: Conversation, question: str, answer: str) -> None:
        self.store.add_conversation_message(
            ConversationMessage(
                conversation_id=conversation.id,
                role="user",
                content=question,
            )
        )
        self.store.add_conversation_message(
            ConversationMessage(
                conversation_id=conversation.id,
                role="assistant",
                content=answer,
            )
        )
        self.store.touch_conversation(conversation_id=conversation.id)

    def _conversation_title(self, question: str) -> str:
        title = " ".join(question.strip().split())
        return title[:40] or "新对话"

    async def query(
        self,
        *,
        kb_id: str,
        question: str,
        top_k: int,
        conversation_id: str | None = None,
        access: AccessContext | None = None,
    ) -> QueryResponse:
        access = access or AccessContext()
        if not question.strip():
            raise ValueError("question is empty")
        kb = self._require_kb(kb_id, access=access)
        self.skills.get_allowed(kb=kb, skill_name="answer_question")
        conversation = self._resolve_conversation(
            kb=kb,
            access=access,
            conversation_id=conversation_id,
            question=question,
        )
        history = self.store.list_conversation_messages(
            conversation_id=conversation.id,
            limit=CONVERSATION_CONTEXT_MESSAGES,
        )
        sources = await self.retriever.retrieve(kb_id=kb.id, query=question, top_k=top_k, access=access)
        answer = await self.llm.answer(kb=kb, instruction=question, sources=sources, history=history)
        self._record_conversation_turn(conversation=conversation, question=question, answer=answer)
        return QueryResponse(answer=answer, sources=sources, conversation_id=conversation.id)

    async def query_stream(
        self,
        *,
        kb_id: str,
        question: str,
        top_k: int,
        conversation_id: str | None = None,
        access: AccessContext | None = None,
    ) -> ConversationStream:
        access = access or AccessContext()
        if not question.strip():
            raise ValueError("question is empty")
        kb = self._require_kb(kb_id, access=access)
        self.skills.get_allowed(kb=kb, skill_name="answer_question")
        conversation = self._resolve_conversation(
            kb=kb,
            access=access,
            conversation_id=conversation_id,
            question=question,
        )
        history = self.store.list_conversation_messages(
            conversation_id=conversation.id,
            limit=CONVERSATION_CONTEXT_MESSAGES,
        )
        sources = await self.retriever.retrieve(kb_id=kb.id, query=question, top_k=top_k, access=access)
        answer_chunks: list[str] = []

        async def stream() -> AsyncIterator[str]:
            try:
                async for chunk in self.llm.stream_answer(
                    kb=kb,
                    instruction=question,
                    sources=sources,
                    history=history,
                ):
                    answer_chunks.append(chunk)
                    yield chunk
            except asyncio.CancelledError:
                raise
            else:
                self._record_conversation_turn(
                    conversation=conversation,
                    question=question,
                    answer="".join(answer_chunks),
                )

        return ConversationStream(conversation_id=conversation.id, chunks=stream())

    async def run_skill(
        self,
        *,
        kb_id: str,
        skill_name: str,
        instruction: str,
        top_k: int,
        access: AccessContext | None = None,
    ) -> SkillResponse:
        access = access or AccessContext()
        if not instruction.strip():
            raise ValueError("instruction is empty")
        kb = self._require_kb(kb_id, access=access)
        skill = self.skills.get_allowed(kb=kb, skill_name=skill_name)
        sources = await self.retriever.retrieve(kb_id=kb.id, query=instruction, top_k=top_k, access=access)
        response = await skill.run(kb=kb, instruction=instruction, sources=sources, llm=self.llm)
        if response.artifact:
            permission_tags = sorted(
                set(kb.permission_tags)
                | set(access.permission_tags)
                | {tag for source in sources for tag in source.permission_tags}
            )
            self.store.add_artifact(
                ArtifactRecord(
                    id=response.artifact.id,
                    knowledge_base_id=kb.id,
                    user_id=access.user_id,
                    tenant_id=kb.tenant_id,
                    filename=response.artifact.filename,
                    media_type=response.artifact.media_type,
                    skill=response.skill,
                    instruction=instruction,
                    permission_tags=permission_tags,
                )
            )
        return response

    def list_artifacts(
        self,
        *,
        kb_id: str,
        access: AccessContext | None = None,
    ) -> list[ArtifactSummary]:
        access = access or AccessContext()
        self._require_kb(kb_id, access=access)
        records = self.store.list_artifacts(kb_id=kb_id, permission_tags=access.permission_tags)
        return [
            ArtifactSummary(
                id=record.id,
                knowledge_base_id=record.knowledge_base_id,
                user_id=record.user_id,
                filename=record.filename,
                media_type=record.media_type,
                skill=record.skill,
                instruction=record.instruction,
                permission_tags=record.permission_tags,
                download_url=f"/knowledge-bases/{record.knowledge_base_id}/artifacts/{record.id}/download",
                created_at=record.created_at,
            )
            for record in records
            if record.tenant_id == access.tenant_id and record.user_id == access.user_id
        ]

    def list_operation_events(
        self,
        *,
        access: AccessContext | None = None,
        kb_id: str | None = None,
        limit: int = 100,
    ) -> list[OperationEvent]:
        access = access or AccessContext()
        if kb_id:
            self._require_kb(kb_id, access=access)
        safe_limit = max(1, min(limit, 200))
        events = self.store.list_operation_events(limit=safe_limit)
        return [
            event
            for event in events
            if event.tenant_id in {"", access.tenant_id}
            and event.user_id == access.user_id
            and (not event.knowledge_base_id or not kb_id or event.knowledge_base_id == kb_id)
        ][:safe_limit]

    def get_artifact_file(
        self,
        *,
        kb_id: str,
        artifact_id: str,
        access: AccessContext | None = None,
    ) -> tuple[ArtifactRecord, Path]:
        artifact = self._require_artifact(kb_id=kb_id, artifact_id=artifact_id, access=access)
        path = self.artifact_dir / artifact.filename
        if not path.exists():
            raise KeyError(f"artifact file '{artifact.filename}' does not exist")
        return artifact, path

    def preview_artifact(
        self,
        *,
        kb_id: str,
        artifact_id: str,
        access: AccessContext | None = None,
    ) -> ArtifactPreview:
        artifact, path = self.get_artifact_file(kb_id=kb_id, artifact_id=artifact_id, access=access)
        data = path.read_bytes()
        if path.suffix.lower() in {".md", ".markdown"}:
            content = data.decode("utf-8", errors="replace")
        else:
            parsed = parse_uploaded_document(
                filename=artifact.filename,
                content_type=artifact.media_type,
                data=data,
                security_policy=self.upload_security_policy,
            )
            content = parsed.content
        return ArtifactPreview(
            id=artifact.id,
            filename=artifact.filename,
            media_type=artifact.media_type,
            skill=artifact.skill,
            instruction=artifact.instruction,
            content=content,
        )

    def delete_artifact(
        self,
        *,
        kb_id: str,
        artifact_id: str,
        access: AccessContext | None = None,
    ) -> None:
        artifact = self._require_artifact(kb_id=kb_id, artifact_id=artifact_id, access=access)
        path = self.artifact_dir / artifact.filename
        deleted = self.store.delete_artifact(kb_id=kb_id, artifact_id=artifact.id)
        if not deleted:
            raise KeyError(f"artifact '{artifact_id}' does not exist")
        if path.exists():
            path.unlink()

    def _require_artifact(
        self,
        *,
        kb_id: str,
        artifact_id: str,
        access: AccessContext | None = None,
    ) -> ArtifactRecord:
        access = access or AccessContext()
        self._require_kb(kb_id, access=access)
        artifact = self.store.get_artifact(kb_id=kb_id, artifact_id=artifact_id)
        if not artifact:
            raise KeyError(f"artifact '{artifact_id}' does not exist")
        if artifact.tenant_id != access.tenant_id:
            raise PermissionError(f"artifact '{artifact_id}' is not in tenant '{access.tenant_id}'")
        if artifact.user_id != access.user_id:
            raise PermissionError(f"artifact '{artifact_id}' was generated by another user")
        self._require_tags(artifact.permission_tags, access=access, subject=f"artifact '{artifact_id}'")
        return artifact

    def _require_kb(self, kb_id: str, access: AccessContext | None = None) -> KnowledgeBase:
        kb = self.store.get_knowledge_base(kb_id)
        if not kb:
            raise KeyError(f"knowledge base '{kb_id}' does not exist")
        if access and kb.tenant_id != access.tenant_id:
            raise PermissionError(f"knowledge base '{kb_id}' is not in tenant '{access.tenant_id}'")
        if access and kb.permission_tags and not set(kb.permission_tags).issubset(set(access.permission_tags)):
            raise PermissionError(f"missing permission tags for knowledge base '{kb_id}'")
        return kb

    def _require_tags(self, required_tags: list[str], *, access: AccessContext, subject: str) -> None:
        if required_tags and not set(required_tags).issubset(set(access.permission_tags)):
            raise PermissionError(f"missing permission tags for {subject}")
