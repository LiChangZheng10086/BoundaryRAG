from __future__ import annotations

import json
from pathlib import Path
from threading import RLock
from uuid import uuid4

from rag_demo.models import ArtifactRecord, Chunk, Document, DocumentSummary, KnowledgeBase


class JsonStore:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    def list_knowledge_bases(self) -> list[KnowledgeBase]:
        return [KnowledgeBase.model_validate(item) for item in self._read_json("knowledge_bases.json", [])]

    def get_knowledge_base(self, kb_id: str) -> KnowledgeBase | None:
        return next((kb for kb in self.list_knowledge_bases() if kb.id == kb_id), None)

    def create_knowledge_base(self, kb: KnowledgeBase) -> KnowledgeBase:
        with self._lock:
            items = self._read_json("knowledge_bases.json", [])
            if any(item["id"] == kb.id for item in items):
                raise ValueError(f"knowledge base '{kb.id}' already exists")
            items.append(kb)
            self._write_json("knowledge_bases.json", [KnowledgeBase.model_validate(item).model_dump() for item in items])
        return kb

    def add_document(self, document: Document) -> Document:
        with self._lock:
            items = self._read_json("documents.json", [])
            items.append(document.model_dump())
            self._write_json("documents.json", items)
        return document

    def list_documents(self, *, kb_id: str, permission_tags: list[str] | None = None) -> list[DocumentSummary]:
        enforce_permissions = permission_tags is not None
        user_tags = set(permission_tags or [])
        documents = [
            Document.model_validate(item)
            for item in self._read_json("documents.json", [])
            if item["knowledge_base_id"] == kb_id
            and (not enforce_permissions or self._is_allowed(item.get("permission_tags", []), user_tags))
        ]
        chunks = self.list_chunks(kb_id=kb_id)
        chunk_counts: dict[str, int] = {}
        for chunk in chunks:
            chunk_counts[chunk.document_id] = chunk_counts.get(chunk.document_id, 0) + 1

        return [
            DocumentSummary(
                id=document.id,
                knowledge_base_id=document.knowledge_base_id,
                title=document.title,
                metadata=document.metadata,
                permission_tags=document.permission_tags,
                status=document.status,
                error=document.error,
                chunk_count=chunk_counts.get(document.id, 0),
                created_at=document.created_at,
            )
            for document in documents
        ]

    def get_document(self, *, kb_id: str, document_id: str) -> Document | None:
        return next(
            (
                Document.model_validate(item)
                for item in self._read_json("documents.json", [])
                if item["knowledge_base_id"] == kb_id and item["id"] == document_id
            ),
            None,
        )

    def update_document(self, *, document: Document) -> Document:
        with self._lock:
            items = self._read_json("documents.json", [])
            updated = False
            for index, item in enumerate(items):
                if item["knowledge_base_id"] == document.knowledge_base_id and item["id"] == document.id:
                    items[index] = document.model_dump()
                    updated = True
                    break
            if not updated:
                raise KeyError(f"document '{document.id}' does not exist")
            self._write_json("documents.json", items)
        return document

    def update_document_status(
        self,
        *,
        kb_id: str,
        document_id: str,
        status: str,
        error: str = "",
    ) -> Document:
        document = self.get_document(kb_id=kb_id, document_id=document_id)
        if not document:
            raise KeyError(f"document '{document_id}' does not exist")
        document = document.model_copy(update={"status": status, "error": error})
        return self.update_document(document=document)

    def delete_document(self, *, kb_id: str, document_id: str) -> bool:
        with self._lock:
            documents = self._read_json("documents.json", [])
            remaining_documents = [
                item
                for item in documents
                if not (item["knowledge_base_id"] == kb_id and item["id"] == document_id)
            ]
            if len(remaining_documents) == len(documents):
                return False

            chunks = self._read_json("chunks.json", [])
            remaining_chunks = [
                item
                for item in chunks
                if not (item["knowledge_base_id"] == kb_id and item["document_id"] == document_id)
            ]
            self._write_json("documents.json", remaining_documents)
            self._write_json("chunks.json", remaining_chunks)
            return True

    def add_chunks(self, chunks: list[Chunk]) -> list[Chunk]:
        with self._lock:
            items = self._read_json("chunks.json", [])
            items.extend(chunk.model_dump() for chunk in chunks)
            self._write_json("chunks.json", items)
        return chunks

    def replace_document_chunks(self, *, kb_id: str, document_id: str, chunks: list[Chunk]) -> list[Chunk]:
        with self._lock:
            items = [
                item
                for item in self._read_json("chunks.json", [])
                if not (item["knowledge_base_id"] == kb_id and item["document_id"] == document_id)
            ]
            items.extend(chunk.model_dump() for chunk in chunks)
            self._write_json("chunks.json", items)
        return chunks

    def add_artifact(self, artifact: ArtifactRecord) -> ArtifactRecord:
        with self._lock:
            items = self._read_json("artifacts.json", [])
            items.append(artifact.model_dump())
            self._write_json("artifacts.json", items)
        return artifact

    def get_artifact(self, *, kb_id: str, artifact_id: str) -> ArtifactRecord | None:
        return next(
            (
                ArtifactRecord.model_validate(item)
                for item in self._read_json("artifacts.json", [])
                if item["knowledge_base_id"] == kb_id and item["id"] == artifact_id
            ),
            None,
        )

    def list_artifacts(self, *, kb_id: str, permission_tags: list[str] | None = None) -> list[ArtifactRecord]:
        enforce_permissions = permission_tags is not None
        user_tags = set(permission_tags or [])
        return [
            ArtifactRecord.model_validate(item)
            for item in self._read_json("artifacts.json", [])
            if item["knowledge_base_id"] == kb_id
            and (not enforce_permissions or self._is_allowed(item.get("permission_tags", []), user_tags))
        ]

    def delete_artifact(self, *, kb_id: str, artifact_id: str) -> bool:
        with self._lock:
            artifacts = self._read_json("artifacts.json", [])
            remaining_artifacts = [
                item
                for item in artifacts
                if not (item["knowledge_base_id"] == kb_id and item["id"] == artifact_id)
            ]
            if len(remaining_artifacts) == len(artifacts):
                return False
            self._write_json("artifacts.json", remaining_artifacts)
            return True

    def list_chunks(
        self,
        *,
        kb_id: str,
        tenant_id: str | None = None,
        permission_tags: list[str] | None = None,
    ) -> list[Chunk]:
        enforce_permissions = permission_tags is not None
        user_tags = set(permission_tags or [])
        return [
            Chunk.model_validate(item)
            for item in self._read_json("chunks.json", [])
            if item["knowledge_base_id"] == kb_id
            and (tenant_id is None or item.get("tenant_id", "default") == tenant_id)
            and (not enforce_permissions or self._is_allowed(item.get("permission_tags", []), user_tags))
        ]

    def _is_allowed(self, required_tags: list[str], user_tags: set[str]) -> bool:
        if not required_tags:
            return True
        return set(required_tags).issubset(user_tags)

    def _read_json(self, filename: str, default: list[dict]) -> list[dict]:
        path = self.data_dir / filename
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_json(self, filename: str, data: list[dict]) -> None:
        path = self.data_dir / filename
        tmp_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp_path.replace(path)
        finally:
            if tmp_path.exists():
                tmp_path.unlink()
