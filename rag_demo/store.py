from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from threading import RLock
from uuid import uuid4

from rag_demo.models import ArtifactRecord, Chunk, Document, DocumentSummary, KnowledgeBase, OperationEvent


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

    def list_documents(
        self,
        *,
        kb_id: str,
        permission_tags: list[str] | None = None,
        chunk_counts: dict[str, int] | None = None,
    ) -> list[DocumentSummary]:
        enforce_permissions = permission_tags is not None
        user_tags = set(permission_tags or [])
        documents = [
            Document.model_validate(item)
            for item in self._read_json("documents.json", [])
            if item["knowledge_base_id"] == kb_id
            and (not enforce_permissions or self._is_allowed(item.get("permission_tags", []), user_tags))
        ]
        chunk_counts = chunk_counts or {}

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

            self._write_json("documents.json", remaining_documents)
            return True

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

    def read_legacy_chunks(self) -> list[Chunk]:
        return [Chunk.model_validate(item) for item in self._read_json("chunks.json", [])]

    def mark_legacy_chunks_migrated(self) -> None:
        path = self.data_dir / "chunks.json"
        if not path.exists():
            return
        migrated_path = self.data_dir / "chunks.json.migrated"
        path.replace(migrated_path)

    def list_operation_events(self, *, limit: int = 100) -> list[OperationEvent]:
        return []

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


class SqliteStore:
    def __init__(self, db_path: Path, *, legacy_data_dir: Path | None = None) -> None:
        self.db_path = db_path
        self.data_dir = legacy_data_dir or db_path.parent
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._init_schema()
        if legacy_data_dir:
            self.migrate_from_json(legacy_data_dir)

    def list_knowledge_bases(self) -> list[KnowledgeBase]:
        with self._connect() as conn:
            rows = conn.execute("select * from knowledge_bases order by created_at asc").fetchall()
        return [self._kb_from_row(row) for row in rows]

    def get_knowledge_base(self, kb_id: str) -> KnowledgeBase | None:
        with self._connect() as conn:
            row = conn.execute("select * from knowledge_bases where id = ?", (kb_id,)).fetchone()
        return self._kb_from_row(row) if row else None

    def create_knowledge_base(self, kb: KnowledgeBase) -> KnowledgeBase:
        with self._lock, self._connect() as conn:
            exists = conn.execute("select 1 from knowledge_bases where id = ?", (kb.id,)).fetchone()
            if exists:
                raise ValueError(f"knowledge base '{kb.id}' already exists")
            self._insert_knowledge_base(conn, kb)
            self._insert_operation(
                conn,
                OperationEvent(
                    event_type="knowledge_base.created",
                    tenant_id=kb.tenant_id,
                    knowledge_base_id=kb.id,
                    message=f"Knowledge base '{kb.id}' created",
                    metadata={"name": kb.name, "allowed_skills": kb.allowed_skills},
                ),
            )
        return kb

    def add_document(self, document: Document) -> Document:
        with self._lock, self._connect() as conn:
            self._insert_document(conn, document)
            self._insert_operation(
                conn,
                OperationEvent(
                    event_type="document.created",
                    tenant_id=self._tenant_for_kb(conn, document.knowledge_base_id),
                    knowledge_base_id=document.knowledge_base_id,
                    document_id=document.id,
                    message=f"Document '{document.title}' created",
                    metadata={"status": document.status, "permission_tags": document.permission_tags},
                ),
            )
        return document

    def list_documents(
        self,
        *,
        kb_id: str,
        permission_tags: list[str] | None = None,
        chunk_counts: dict[str, int] | None = None,
    ) -> list[DocumentSummary]:
        with self._connect() as conn:
            rows = conn.execute(
                "select * from documents where knowledge_base_id = ? order by created_at desc",
                (kb_id,),
            ).fetchall()
        enforce_permissions = permission_tags is not None
        user_tags = set(permission_tags or [])
        chunk_counts = chunk_counts or {}
        documents = [
            self._document_from_row(row)
            for row in rows
            if not enforce_permissions or self._is_allowed(self._json_loads(row["permission_tags_json"], []), user_tags)
        ]
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
        with self._connect() as conn:
            row = conn.execute(
                "select * from documents where knowledge_base_id = ? and id = ?",
                (kb_id, document_id),
            ).fetchone()
        return self._document_from_row(row) if row else None

    def update_document(self, *, document: Document) -> Document:
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                """
                update documents
                set title = ?, content = ?, metadata_json = ?, permission_tags_json = ?,
                    status = ?, error = ?, created_at = ?
                where knowledge_base_id = ? and id = ?
                """,
                (
                    document.title,
                    document.content,
                    self._json_dumps(document.metadata),
                    self._json_dumps(document.permission_tags),
                    document.status,
                    document.error,
                    document.created_at,
                    document.knowledge_base_id,
                    document.id,
                ),
            )
            if cursor.rowcount == 0:
                raise KeyError(f"document '{document.id}' does not exist")
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
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "update documents set status = ?, error = ? where knowledge_base_id = ? and id = ?",
                (status, error, kb_id, document_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(f"document '{document_id}' does not exist")
            self._insert_operation(
                conn,
                OperationEvent(
                    event_type=f"document.{status}",
                    tenant_id=self._tenant_for_kb(conn, kb_id),
                    knowledge_base_id=kb_id,
                    document_id=document_id,
                    message=f"Document '{document_id}' status changed to {status}",
                    metadata={"status": status, "error": error},
                ),
            )
        return document

    def delete_document(self, *, kb_id: str, document_id: str) -> bool:
        with self._lock, self._connect() as conn:
            document = conn.execute(
                "select title from documents where knowledge_base_id = ? and id = ?",
                (kb_id, document_id),
            ).fetchone()
            if not document:
                return False
            conn.execute("delete from documents where knowledge_base_id = ? and id = ?", (kb_id, document_id))
            self._insert_operation(
                conn,
                OperationEvent(
                    event_type="document.deleted",
                    tenant_id=self._tenant_for_kb(conn, kb_id),
                    knowledge_base_id=kb_id,
                    document_id=document_id,
                    message=f"Document '{document_id}' deleted",
                    metadata={"title": document["title"]},
                ),
            )
            return True

    def add_artifact(self, artifact: ArtifactRecord) -> ArtifactRecord:
        with self._lock, self._connect() as conn:
            self._insert_artifact(conn, artifact)
            self._insert_operation(
                conn,
                OperationEvent(
                    event_type="artifact.created",
                    user_id=artifact.user_id,
                    tenant_id=artifact.tenant_id,
                    knowledge_base_id=artifact.knowledge_base_id,
                    artifact_id=artifact.id,
                    message=f"Artifact '{artifact.filename}' created",
                    metadata={"skill": artifact.skill, "filename": artifact.filename},
                ),
            )
        return artifact

    def get_artifact(self, *, kb_id: str, artifact_id: str) -> ArtifactRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "select * from artifacts where knowledge_base_id = ? and id = ?",
                (kb_id, artifact_id),
            ).fetchone()
        return self._artifact_from_row(row) if row else None

    def list_artifacts(self, *, kb_id: str, permission_tags: list[str] | None = None) -> list[ArtifactRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "select * from artifacts where knowledge_base_id = ? order by created_at desc",
                (kb_id,),
            ).fetchall()
        enforce_permissions = permission_tags is not None
        user_tags = set(permission_tags or [])
        return [
            self._artifact_from_row(row)
            for row in rows
            if not enforce_permissions or self._is_allowed(self._json_loads(row["permission_tags_json"], []), user_tags)
        ]

    def delete_artifact(self, *, kb_id: str, artifact_id: str) -> bool:
        with self._lock, self._connect() as conn:
            artifact = conn.execute(
                "select * from artifacts where knowledge_base_id = ? and id = ?",
                (kb_id, artifact_id),
            ).fetchone()
            if not artifact:
                return False
            conn.execute("delete from artifacts where knowledge_base_id = ? and id = ?", (kb_id, artifact_id))
            self._insert_operation(
                conn,
                OperationEvent(
                    event_type="artifact.deleted",
                    user_id=artifact["user_id"],
                    tenant_id=artifact["tenant_id"],
                    knowledge_base_id=kb_id,
                    artifact_id=artifact_id,
                    message=f"Artifact '{artifact_id}' deleted",
                    metadata={"filename": artifact["filename"]},
                ),
            )
            return True

    def list_operation_events(self, *, limit: int = 100) -> list[OperationEvent]:
        with self._connect() as conn:
            rows = conn.execute(
                "select * from operation_events order by created_at desc limit ?",
                (limit,),
            ).fetchall()
        return [self._operation_from_row(row) for row in rows]

    def read_legacy_chunks(self) -> list[Chunk]:
        return [Chunk.model_validate(item) for item in self._read_json("chunks.json", [])]

    def mark_legacy_chunks_migrated(self) -> None:
        path = self.data_dir / "chunks.json"
        if not path.exists():
            return
        migrated_path = self.data_dir / "chunks.json.migrated"
        path.replace(migrated_path)

    def migrate_from_json(self, data_dir: Path) -> None:
        with self._lock, self._connect() as conn:
            imported = {
                "knowledge_bases": self._migrate_knowledge_bases(conn, data_dir),
                "documents": self._migrate_documents(conn, data_dir),
                "artifacts": self._migrate_artifacts(conn, data_dir),
            }
            if any(imported.values()):
                self._insert_operation(
                    conn,
                    OperationEvent(
                        event_type="storage.legacy_json_imported",
                        message="Legacy JSON metadata imported into SQLite",
                        metadata=imported,
                    ),
                    ignore_existing=True,
                )

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                create table if not exists knowledge_bases (
                    id text primary key,
                    name text not null,
                    description text not null default '',
                    tenant_id text not null default 'default',
                    allowed_skills_json text not null,
                    permission_tags_json text not null,
                    created_at text not null
                );

                create table if not exists documents (
                    id text primary key,
                    knowledge_base_id text not null,
                    title text not null,
                    content text not null,
                    metadata_json text not null,
                    permission_tags_json text not null,
                    status text not null,
                    error text not null,
                    created_at text not null
                );

                create table if not exists artifacts (
                    id text primary key,
                    knowledge_base_id text not null,
                    user_id text not null,
                    tenant_id text not null,
                    filename text not null,
                    media_type text not null,
                    skill text not null,
                    instruction text not null,
                    permission_tags_json text not null,
                    created_at text not null
                );

                create table if not exists operation_events (
                    id text primary key,
                    event_type text not null,
                    user_id text not null,
                    tenant_id text not null,
                    knowledge_base_id text not null,
                    document_id text not null,
                    artifact_id text not null,
                    message text not null,
                    metadata_json text not null,
                    created_at text not null
                );

                create index if not exists idx_kb_tenant on knowledge_bases(tenant_id);
                create index if not exists idx_documents_kb on documents(knowledge_base_id);
                create index if not exists idx_documents_status on documents(status);
                create index if not exists idx_artifacts_kb_user on artifacts(knowledge_base_id, user_id);
                create index if not exists idx_operation_events_created on operation_events(created_at);
                create index if not exists idx_operation_events_kb on operation_events(knowledge_base_id);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("pragma journal_mode = wal")
        conn.execute("pragma foreign_keys = on")
        return conn

    def _insert_knowledge_base(self, conn: sqlite3.Connection, kb: KnowledgeBase, *, ignore: bool = False) -> None:
        clause = "insert or ignore" if ignore else "insert"
        conn.execute(
            f"""
            {clause} into knowledge_bases (
                id, name, description, tenant_id, allowed_skills_json, permission_tags_json, created_at
            ) values (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                kb.id,
                kb.name,
                kb.description,
                kb.tenant_id,
                self._json_dumps(kb.allowed_skills),
                self._json_dumps(kb.permission_tags),
                kb.created_at,
            ),
        )

    def _insert_document(self, conn: sqlite3.Connection, document: Document, *, ignore: bool = False) -> None:
        clause = "insert or ignore" if ignore else "insert"
        conn.execute(
            f"""
            {clause} into documents (
                id, knowledge_base_id, title, content, metadata_json, permission_tags_json,
                status, error, created_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                document.id,
                document.knowledge_base_id,
                document.title,
                document.content,
                self._json_dumps(document.metadata),
                self._json_dumps(document.permission_tags),
                document.status,
                document.error,
                document.created_at,
            ),
        )

    def _insert_artifact(self, conn: sqlite3.Connection, artifact: ArtifactRecord, *, ignore: bool = False) -> None:
        clause = "insert or ignore" if ignore else "insert"
        conn.execute(
            f"""
            {clause} into artifacts (
                id, knowledge_base_id, user_id, tenant_id, filename, media_type, skill,
                instruction, permission_tags_json, created_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                artifact.id,
                artifact.knowledge_base_id,
                artifact.user_id,
                artifact.tenant_id,
                artifact.filename,
                artifact.media_type,
                artifact.skill,
                artifact.instruction,
                self._json_dumps(artifact.permission_tags),
                artifact.created_at,
            ),
        )

    def _insert_operation(
        self,
        conn: sqlite3.Connection,
        event: OperationEvent,
        *,
        ignore_existing: bool = False,
    ) -> None:
        clause = "insert or ignore" if ignore_existing else "insert"
        conn.execute(
            f"""
            {clause} into operation_events (
                id, event_type, user_id, tenant_id, knowledge_base_id, document_id,
                artifact_id, message, metadata_json, created_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.id,
                event.event_type,
                event.user_id,
                event.tenant_id,
                event.knowledge_base_id,
                event.document_id,
                event.artifact_id,
                event.message,
                self._json_dumps(event.metadata),
                event.created_at,
            ),
        )

    def _migrate_knowledge_bases(self, conn: sqlite3.Connection, data_dir: Path) -> int:
        before = conn.total_changes
        for item in self._read_json_from(data_dir, "knowledge_bases.json", []):
            self._insert_knowledge_base(conn, KnowledgeBase.model_validate(item), ignore=True)
        return conn.total_changes - before

    def _migrate_documents(self, conn: sqlite3.Connection, data_dir: Path) -> int:
        before = conn.total_changes
        for item in self._read_json_from(data_dir, "documents.json", []):
            self._insert_document(conn, Document.model_validate(item), ignore=True)
        return conn.total_changes - before

    def _migrate_artifacts(self, conn: sqlite3.Connection, data_dir: Path) -> int:
        before = conn.total_changes
        for item in self._read_json_from(data_dir, "artifacts.json", []):
            self._insert_artifact(conn, ArtifactRecord.model_validate(item), ignore=True)
        return conn.total_changes - before

    def _tenant_for_kb(self, conn: sqlite3.Connection, kb_id: str) -> str:
        row = conn.execute("select tenant_id from knowledge_bases where id = ?", (kb_id,)).fetchone()
        return row["tenant_id"] if row else "default"

    def _kb_from_row(self, row: sqlite3.Row) -> KnowledgeBase:
        return KnowledgeBase(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            tenant_id=row["tenant_id"],
            allowed_skills=self._json_loads(row["allowed_skills_json"], []),
            permission_tags=self._json_loads(row["permission_tags_json"], []),
            created_at=row["created_at"],
        )

    def _document_from_row(self, row: sqlite3.Row) -> Document:
        return Document(
            id=row["id"],
            knowledge_base_id=row["knowledge_base_id"],
            title=row["title"],
            content=row["content"],
            metadata=self._json_loads(row["metadata_json"], {}),
            permission_tags=self._json_loads(row["permission_tags_json"], []),
            status=row["status"],
            error=row["error"],
            created_at=row["created_at"],
        )

    def _artifact_from_row(self, row: sqlite3.Row) -> ArtifactRecord:
        return ArtifactRecord(
            id=row["id"],
            knowledge_base_id=row["knowledge_base_id"],
            user_id=row["user_id"],
            tenant_id=row["tenant_id"],
            filename=row["filename"],
            media_type=row["media_type"],
            skill=row["skill"],
            instruction=row["instruction"],
            permission_tags=self._json_loads(row["permission_tags_json"], []),
            created_at=row["created_at"],
        )

    def _operation_from_row(self, row: sqlite3.Row) -> OperationEvent:
        return OperationEvent(
            id=row["id"],
            event_type=row["event_type"],
            user_id=row["user_id"],
            tenant_id=row["tenant_id"],
            knowledge_base_id=row["knowledge_base_id"],
            document_id=row["document_id"],
            artifact_id=row["artifact_id"],
            message=row["message"],
            metadata=self._json_loads(row["metadata_json"], {}),
            created_at=row["created_at"],
        )

    def _is_allowed(self, required_tags: list[str], user_tags: set[str]) -> bool:
        if not required_tags:
            return True
        return set(required_tags).issubset(user_tags)

    def _read_json(self, filename: str, default: list[dict]) -> list[dict]:
        return self._read_json_from(self.data_dir, filename, default)

    def _read_json_from(self, data_dir: Path, filename: str, default: list[dict]) -> list[dict]:
        path = data_dir / filename
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))

    def _json_dumps(self, value: object) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    def _json_loads(self, value: str, default: object) -> object:
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return default
