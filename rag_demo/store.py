from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from threading import RLock
from uuid import uuid4

from rag_demo.models import (
    ArtifactRecord,
    Chunk,
    Conversation,
    ConversationMessage,
    Document,
    DocumentSummary,
    KnowledgeBase,
    OperationEvent,
    UserAccount,
    utc_now,
)


class JsonStore:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    def list_knowledge_bases(self) -> list[KnowledgeBase]:
        return [KnowledgeBase.model_validate(item) for item in self._read_json("knowledge_bases.json", [])]

    def get_knowledge_base(self, kb_id: str) -> KnowledgeBase | None:
        return next((kb for kb in self.list_knowledge_bases() if kb.id == kb_id), None)

    def create_knowledge_base(self, kb: KnowledgeBase, *, user_id: str = "system") -> KnowledgeBase:
        with self._lock:
            items = self._read_json("knowledge_bases.json", [])
            if any(item["id"] == kb.id for item in items):
                raise ValueError(f"knowledge base '{kb.id}' already exists")
            items.append(kb)
            self._write_json("knowledge_bases.json", [KnowledgeBase.model_validate(item).model_dump() for item in items])
        return kb

    def delete_knowledge_base(self, kb_id: str, *, user_id: str = "system") -> bool:
        with self._lock:
            items = self._read_json("knowledge_bases.json", [])
            remaining = [item for item in items if item["id"] != kb_id]
            if len(remaining) == len(items):
                return False
            self._write_json("knowledge_bases.json", remaining)
            self._write_json(
                "documents.json",
                [item for item in self._read_json("documents.json", []) if item["knowledge_base_id"] != kb_id],
            )
            self._write_json(
                "artifacts.json",
                [item for item in self._read_json("artifacts.json", []) if item["knowledge_base_id"] != kb_id],
            )
            conversations = self._read_json("conversations.json", [])
            deleted_conversation_ids = {
                item["id"] for item in conversations if item["knowledge_base_id"] == kb_id
            }
            self._write_json(
                "conversations.json",
                [item for item in conversations if item["knowledge_base_id"] != kb_id],
            )
            self._write_json(
                "conversation_messages.json",
                [
                    item
                    for item in self._read_json("conversation_messages.json", [])
                    if item["conversation_id"] not in deleted_conversation_ids
                ],
            )
            self._write_json(
                "chunks.json",
                [item for item in self._read_json("chunks.json", []) if item["knowledge_base_id"] != kb_id],
            )
            return True

    def add_document(self, document: Document, *, user_id: str = "system") -> Document:
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
        user_id: str = "system",
    ) -> Document:
        document = self.get_document(kb_id=kb_id, document_id=document_id)
        if not document:
            raise KeyError(f"document '{document_id}' does not exist")
        document = document.model_copy(update={"status": status, "error": error})
        return self.update_document(document=document)

    def delete_document(self, *, kb_id: str, document_id: str, user_id: str = "system") -> bool:
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

    def create_conversation(self, conversation: Conversation) -> Conversation:
        with self._lock:
            items = self._read_json("conversations.json", [])
            if any(item["id"] == conversation.id for item in items):
                raise ValueError(f"conversation '{conversation.id}' already exists")
            items.append(conversation.model_dump())
            self._write_json("conversations.json", items)
        return conversation

    def get_conversation(self, conversation_id: str) -> Conversation | None:
        return next(
            (
                Conversation.model_validate(item)
                for item in self._read_json("conversations.json", [])
                if item["id"] == conversation_id
            ),
            None,
        )

    def list_conversations(
        self,
        *,
        kb_id: str,
        user_id: str,
        tenant_id: str,
        limit: int = 50,
    ) -> list[Conversation]:
        conversations = [
            Conversation.model_validate(item)
            for item in self._read_json("conversations.json", [])
            if item["knowledge_base_id"] == kb_id
            and item.get("user_id") == user_id
            and item.get("tenant_id") == tenant_id
        ]
        conversations.sort(key=lambda item: item.updated_at, reverse=True)
        return conversations[:limit]

    def touch_conversation(self, *, conversation_id: str, title: str | None = None) -> Conversation:
        with self._lock:
            items = self._read_json("conversations.json", [])
            updated_at = utc_now()
            for index, item in enumerate(items):
                if item["id"] == conversation_id:
                    item = {**item, "updated_at": updated_at}
                    if title is not None:
                        item["title"] = title
                    items[index] = item
                    self._write_json("conversations.json", items)
                    return Conversation.model_validate(item)
            raise KeyError(f"conversation '{conversation_id}' does not exist")

    def add_conversation_message(self, message: ConversationMessage) -> ConversationMessage:
        with self._lock:
            items = self._read_json("conversation_messages.json", [])
            items.append(message.model_dump())
            self._write_json("conversation_messages.json", items)
        return message

    def list_conversation_messages(self, *, conversation_id: str, limit: int = 12) -> list[ConversationMessage]:
        messages = [
            ConversationMessage.model_validate(item)
            for item in self._read_json("conversation_messages.json", [])
            if item["conversation_id"] == conversation_id
        ]
        messages.sort(key=lambda item: item.created_at)
        return messages[-limit:]

    def read_legacy_chunks(self) -> list[Chunk]:
        return [Chunk.model_validate(item) for item in self._read_json("chunks.json", [])]

    def mark_legacy_chunks_migrated(self) -> None:
        path = self.data_dir / "chunks.json"
        if not path.exists():
            return
        migrated_path = self.data_dir / "chunks.json.migrated"
        path.replace(migrated_path)

    def get_user(self, username: str) -> UserAccount | None:
        return next(
            (
                UserAccount.model_validate(item)
                for item in self._read_json("users.json", [])
                if item["username"] == username
            ),
            None,
        )

    def upsert_user(self, user: UserAccount) -> UserAccount:
        with self._lock:
            items = self._read_json("users.json", [])
            updated = False
            for index, item in enumerate(items):
                if item["username"] == user.username:
                    items[index] = user.model_dump()
                    updated = True
                    break
            if not updated:
                items.append(user.model_dump())
            self._write_json("users.json", items)
        return user

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
        self.seed_default_users()
        if legacy_data_dir:
            self.migrate_from_json(legacy_data_dir)

    def list_knowledge_bases(self) -> list[KnowledgeBase]:
        with self._connect() as conn:
            rows = conn.execute("select * from knowledge_bases order by created_at asc").fetchall()
        return [self._kb_from_row(row) for row in rows]

    def get_user(self, username: str) -> UserAccount | None:
        with self._connect() as conn:
            row = conn.execute("select * from users where username = ?", (username,)).fetchone()
        return self._user_from_row(row) if row else None

    def upsert_user(self, user: UserAccount) -> UserAccount:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                insert into users (
                    username, password_hash, role, tenant_id, permission_tags_json,
                    active, created_at, updated_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(username) do update set
                    password_hash = excluded.password_hash,
                    role = excluded.role,
                    tenant_id = excluded.tenant_id,
                    permission_tags_json = excluded.permission_tags_json,
                    active = excluded.active,
                    updated_at = excluded.updated_at
                """,
                (
                    user.username,
                    user.password_hash,
                    user.role,
                    user.tenant_id,
                    self._json_dumps(user.permission_tags),
                    1 if user.active else 0,
                    user.created_at,
                    user.updated_at,
                ),
            )
        return user

    def seed_default_users(self) -> None:
        from rag_demo.auth import hash_password

        now = utc_now()
        defaults = [
            UserAccount(
                username="rag_user",
                password_hash=hash_password("rag_user123456"),
                role="admin",
                tenant_id="default",
                permission_tags=[],
                created_at=now,
                updated_at=now,
            ),
            UserAccount(
                username="lcz10086",
                password_hash=hash_password("lcz123456"),
                role="user",
                tenant_id="default",
                permission_tags=[],
                created_at=now,
                updated_at=now,
            ),
        ]
        for user in defaults:
            if not self.get_user(user.username):
                self.upsert_user(user)

    def get_knowledge_base(self, kb_id: str) -> KnowledgeBase | None:
        with self._connect() as conn:
            row = conn.execute("select * from knowledge_bases where id = ?", (kb_id,)).fetchone()
        return self._kb_from_row(row) if row else None

    def create_knowledge_base(self, kb: KnowledgeBase, *, user_id: str = "system") -> KnowledgeBase:
        with self._lock, self._connect() as conn:
            exists = conn.execute("select 1 from knowledge_bases where id = ?", (kb.id,)).fetchone()
            if exists:
                raise ValueError(f"knowledge base '{kb.id}' already exists")
            self._insert_knowledge_base(conn, kb)
            self._insert_operation(
                conn,
                OperationEvent(
                    event_type="knowledge_base.created",
                    user_id=user_id,
                    tenant_id=kb.tenant_id,
                    knowledge_base_id=kb.id,
                    message=f"Knowledge base '{kb.id}' created",
                    metadata={"name": kb.name, "allowed_skills": kb.allowed_skills},
                ),
            )
        return kb

    def delete_knowledge_base(self, kb_id: str, *, user_id: str = "system") -> bool:
        with self._lock, self._connect() as conn:
            row = conn.execute("select id, tenant_id from knowledge_bases where id = ?", (kb_id,)).fetchone()
            if not row:
                return False
            conn.execute("delete from knowledge_bases where id = ?", (kb_id,))
            conn.execute("delete from documents where knowledge_base_id = ?", (kb_id,))
            conn.execute("delete from artifacts where knowledge_base_id = ?", (kb_id,))
            conn.execute(
                """
                delete from conversation_messages
                where conversation_id in (
                    select id from conversations where knowledge_base_id = ?
                )
                """,
                (kb_id,),
            )
            conn.execute("delete from conversations where knowledge_base_id = ?", (kb_id,))
            self._insert_operation(
                conn,
                OperationEvent(
                    event_type="knowledge_base.deleted",
                    user_id=user_id,
                    tenant_id=row["tenant_id"],
                    knowledge_base_id=kb_id,
                    message=f"Knowledge base '{kb_id}' deleted",
                ),
            )
            return True

    def add_document(self, document: Document, *, user_id: str = "system") -> Document:
        with self._lock, self._connect() as conn:
            self._insert_document(conn, document)
            self._insert_operation(
                conn,
                OperationEvent(
                    event_type="document.created",
                    user_id=user_id,
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
        user_id: str = "system",
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
                    user_id=user_id,
                    tenant_id=self._tenant_for_kb(conn, kb_id),
                    knowledge_base_id=kb_id,
                    document_id=document_id,
                    message=f"Document '{document_id}' status changed to {status}",
                    metadata={"status": status, "error": error},
                ),
            )
        return document

    def delete_document(self, *, kb_id: str, document_id: str, user_id: str = "system") -> bool:
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
                    user_id=user_id,
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

    def create_conversation(self, conversation: Conversation) -> Conversation:
        with self._lock, self._connect() as conn:
            self._insert_conversation(conn, conversation)
            self._insert_operation(
                conn,
                OperationEvent(
                    event_type="conversation.created",
                    user_id=conversation.user_id,
                    tenant_id=conversation.tenant_id,
                    knowledge_base_id=conversation.knowledge_base_id,
                    message=f"Conversation '{conversation.id}' created",
                    metadata={"title": conversation.title},
                ),
            )
        return conversation

    def get_conversation(self, conversation_id: str) -> Conversation | None:
        with self._connect() as conn:
            row = conn.execute("select * from conversations where id = ?", (conversation_id,)).fetchone()
        return self._conversation_from_row(row) if row else None

    def list_conversations(
        self,
        *,
        kb_id: str,
        user_id: str,
        tenant_id: str,
        limit: int = 50,
    ) -> list[Conversation]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select * from conversations
                where knowledge_base_id = ? and user_id = ? and tenant_id = ?
                order by updated_at desc
                limit ?
                """,
                (kb_id, user_id, tenant_id, limit),
            ).fetchall()
        return [self._conversation_from_row(row) for row in rows]

    def touch_conversation(self, *, conversation_id: str, title: str | None = None) -> Conversation:
        updated_at = utc_now()
        with self._lock, self._connect() as conn:
            if title is None:
                cursor = conn.execute(
                    "update conversations set updated_at = ? where id = ?",
                    (updated_at, conversation_id),
                )
            else:
                cursor = conn.execute(
                    "update conversations set title = ?, updated_at = ? where id = ?",
                    (title, updated_at, conversation_id),
                )
            if cursor.rowcount == 0:
                raise KeyError(f"conversation '{conversation_id}' does not exist")
            row = conn.execute("select * from conversations where id = ?", (conversation_id,)).fetchone()
        return self._conversation_from_row(row)

    def add_conversation_message(self, message: ConversationMessage) -> ConversationMessage:
        with self._lock, self._connect() as conn:
            self._insert_conversation_message(conn, message)
        return message

    def list_conversation_messages(self, *, conversation_id: str, limit: int = 12) -> list[ConversationMessage]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select * from (
                    select * from conversation_messages
                    where conversation_id = ?
                    order by created_at desc
                    limit ?
                )
                order by created_at asc
                """,
                (conversation_id, limit),
            ).fetchall()
        return [self._conversation_message_from_row(row) for row in rows]

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
                    owner_user_id text not null default '',
                    allowed_skills_json text not null,
                    permission_tags_json text not null,
                    created_at text not null
                );

                create table if not exists users (
                    username text primary key,
                    password_hash text not null,
                    role text not null,
                    tenant_id text not null default 'default',
                    permission_tags_json text not null,
                    active integer not null default 1,
                    created_at text not null,
                    updated_at text not null
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

                create table if not exists conversations (
                    id text primary key,
                    knowledge_base_id text not null,
                    user_id text not null,
                    tenant_id text not null,
                    title text not null,
                    created_at text not null,
                    updated_at text not null
                );

                create table if not exists conversation_messages (
                    id text primary key,
                    conversation_id text not null,
                    role text not null,
                    content text not null,
                    created_at text not null
                );

                """
            )
            # Existing local SQLite files may predate user ownership. Add new
            # columns before creating indexes that depend on them.
            self._ensure_column(
                conn,
                table_name="knowledge_bases",
                column_name="owner_user_id",
                column_sql="owner_user_id text not null default ''",
            )
            conn.executescript(
                """
                create index if not exists idx_users_role on users(role);
                create index if not exists idx_kb_tenant on knowledge_bases(tenant_id);
                create index if not exists idx_kb_tenant_owner on knowledge_bases(tenant_id, owner_user_id);
                create index if not exists idx_documents_kb on documents(knowledge_base_id);
                create index if not exists idx_documents_status on documents(status);
                create index if not exists idx_artifacts_kb_user on artifacts(knowledge_base_id, user_id);
                create index if not exists idx_operation_events_created on operation_events(created_at);
                create index if not exists idx_operation_events_kb on operation_events(knowledge_base_id);
                create index if not exists idx_conversations_kb_user on conversations(knowledge_base_id, user_id, tenant_id);
                create index if not exists idx_conversation_messages_conv on conversation_messages(conversation_id, created_at);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("pragma journal_mode = wal")
        conn.execute("pragma foreign_keys = on")
        return conn

    def _ensure_column(
        self,
        conn: sqlite3.Connection,
        *,
        table_name: str,
        column_name: str,
        column_sql: str,
    ) -> None:
        columns = {row["name"] for row in conn.execute(f"pragma table_info({table_name})").fetchall()}
        if column_name not in columns:
            conn.execute(f"alter table {table_name} add column {column_sql}")

    def _insert_knowledge_base(self, conn: sqlite3.Connection, kb: KnowledgeBase, *, ignore: bool = False) -> None:
        clause = "insert or ignore" if ignore else "insert"
        conn.execute(
            f"""
            {clause} into knowledge_bases (
                id, name, description, tenant_id, owner_user_id,
                allowed_skills_json, permission_tags_json, created_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                kb.id,
                kb.name,
                kb.description,
                kb.tenant_id,
                kb.owner_user_id,
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

    def _insert_conversation(self, conn: sqlite3.Connection, conversation: Conversation) -> None:
        conn.execute(
            """
            insert into conversations (
                id, knowledge_base_id, user_id, tenant_id, title, created_at, updated_at
            ) values (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                conversation.id,
                conversation.knowledge_base_id,
                conversation.user_id,
                conversation.tenant_id,
                conversation.title,
                conversation.created_at,
                conversation.updated_at,
            ),
        )

    def _insert_conversation_message(
        self,
        conn: sqlite3.Connection,
        message: ConversationMessage,
    ) -> None:
        conn.execute(
            """
            insert into conversation_messages (
                id, conversation_id, role, content, created_at
            ) values (?, ?, ?, ?, ?)
            """,
            (
                message.id,
                message.conversation_id,
                message.role,
                message.content,
                message.created_at,
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
            owner_user_id=row["owner_user_id"],
            allowed_skills=self._json_loads(row["allowed_skills_json"], []),
            permission_tags=self._json_loads(row["permission_tags_json"], []),
            created_at=row["created_at"],
        )

    def _user_from_row(self, row: sqlite3.Row) -> UserAccount:
        return UserAccount(
            username=row["username"],
            password_hash=row["password_hash"],
            role=row["role"],
            tenant_id=row["tenant_id"],
            permission_tags=self._json_loads(row["permission_tags_json"], []),
            active=bool(row["active"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
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

    def _conversation_from_row(self, row: sqlite3.Row) -> Conversation:
        return Conversation(
            id=row["id"],
            knowledge_base_id=row["knowledge_base_id"],
            user_id=row["user_id"],
            tenant_id=row["tenant_id"],
            title=row["title"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _conversation_message_from_row(self, row: sqlite3.Row) -> ConversationMessage:
        return ConversationMessage(
            id=row["id"],
            conversation_id=row["conversation_id"],
            role=row["role"],
            content=row["content"],
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
