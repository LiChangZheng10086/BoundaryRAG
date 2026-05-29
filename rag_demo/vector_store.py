from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Protocol

from pymilvus import DataType, MilvusClient

from rag_demo.models import Chunk


@dataclass(frozen=True)
class ChunkSearchMatch:
    chunk: Chunk
    vector_score: float


class ChunkStore(Protocol):
    def replace_document_chunks(self, *, kb_id: str, document_id: str, chunks: list[Chunk]) -> list[Chunk]:
        raise NotImplementedError

    def delete_document_chunks(self, *, kb_id: str, document_id: str) -> None:
        raise NotImplementedError

    def list_chunks(
        self,
        *,
        kb_id: str,
        tenant_id: str | None = None,
        permission_tags: list[str] | None = None,
    ) -> list[Chunk]:
        raise NotImplementedError

    def count_chunks_by_document(
        self,
        *,
        kb_id: str,
        tenant_id: str | None = None,
        permission_tags: list[str] | None = None,
    ) -> dict[str, int]:
        raise NotImplementedError

    def search_chunks(
        self,
        *,
        kb_id: str,
        tenant_id: str,
        query_embedding: list[float],
        limit: int,
    ) -> list[ChunkSearchMatch]:
        raise NotImplementedError


class MilvusChunkStore:
    _VECTOR_FIELD = "embedding"
    _OUTPUT_FIELDS = [
        "id",
        "knowledge_base_id",
        "document_id",
        "title",
        "text",
        "metadata_json",
        "tenant_id",
        "permission_tags_json",
        "created_at",
        "embedding",
    ]

    def __init__(self, *, uri: Path | str, collection_name: str) -> None:
        self.uri = Path(uri)
        self.collection_name = collection_name
        self.uri.parent.mkdir(parents=True, exist_ok=True)
        self._client = MilvusClient(uri=str(self.uri))
        self._lock = RLock()

    def replace_document_chunks(self, *, kb_id: str, document_id: str, chunks: list[Chunk]) -> list[Chunk]:
        with self._lock:
            self.delete_document_chunks(kb_id=kb_id, document_id=document_id)
            if not chunks:
                return []
            for dimension, dimension_chunks in self._chunks_by_dimension(chunks).items():
                collection_name = self._collection_name_for_dimension(dimension)
                self._ensure_collection(collection_name=collection_name, dimension=dimension)
                self._client.insert(
                    collection_name=collection_name,
                    data=[self._chunk_to_row(chunk) for chunk in dimension_chunks],
                )
                self._flush(collection_name)
            return chunks

    def upsert_chunks(self, chunks: list[Chunk]) -> list[Chunk]:
        with self._lock:
            if not chunks:
                return []
            for dimension, dimension_chunks in self._chunks_by_dimension(chunks).items():
                collection_name = self._collection_name_for_dimension(dimension)
                self._ensure_collection(collection_name=collection_name, dimension=dimension)
                self._client.upsert(
                    collection_name=collection_name,
                    data=[self._chunk_to_row(chunk) for chunk in dimension_chunks],
                )
                self._flush(collection_name)
            return chunks

    def delete_document_chunks(self, *, kb_id: str, document_id: str) -> None:
        for collection_name in self._active_collection_names():
            self._client.delete(
                collection_name=collection_name,
                filter=(
                    f"knowledge_base_id == {self._literal(kb_id)} "
                    f"and document_id == {self._literal(document_id)}"
                ),
            )
            self._flush(collection_name)

    def list_chunks(
        self,
        *,
        kb_id: str,
        tenant_id: str | None = None,
        permission_tags: list[str] | None = None,
    ) -> list[Chunk]:
        rows: list[dict] = []
        for collection_name in self._active_collection_names():
            rows.extend(
                self._query_rows(
                    collection_name,
                    self._filter_expression(kb_id=kb_id, tenant_id=tenant_id),
                    output_fields=self._OUTPUT_FIELDS,
                )
            )
        chunks = [self._row_to_chunk(row) for row in rows]
        if permission_tags is None:
            return chunks
        return [chunk for chunk in chunks if self._is_allowed(chunk.permission_tags, set(permission_tags))]

    def count_chunks_by_document(
        self,
        *,
        kb_id: str,
        tenant_id: str | None = None,
        permission_tags: list[str] | None = None,
    ) -> dict[str, int]:
        chunks = self.list_chunks(kb_id=kb_id, tenant_id=tenant_id, permission_tags=permission_tags)
        counts: dict[str, int] = {}
        for chunk in chunks:
            counts[chunk.document_id] = counts.get(chunk.document_id, 0) + 1
        return counts

    def search_chunks(
        self,
        *,
        kb_id: str,
        tenant_id: str,
        query_embedding: list[float],
        limit: int,
    ) -> list[ChunkSearchMatch]:
        if not query_embedding or limit < 1:
            return []
        collection_names = self._collection_names_for_dimension(len(query_embedding))
        if not collection_names:
            return []
        matches: list[ChunkSearchMatch] = []
        for collection_name in collection_names:
            results = self._client.search(
                collection_name=collection_name,
                data=[query_embedding],
                anns_field=self._VECTOR_FIELD,
                filter=self._filter_expression(kb_id=kb_id, tenant_id=tenant_id),
                limit=limit,
                output_fields=self._OUTPUT_FIELDS,
            )
            for hit in results[0] if results else []:
                entity = dict(hit.get("entity") or {})
                entity["id"] = entity.get("id") or hit.get("id")
                distance = float(hit.get("distance") or 0.0)
                matches.append(
                    ChunkSearchMatch(
                        chunk=self._row_to_chunk(entity),
                        vector_score=max(0.0, 1.0 - distance),
                    )
                )
        matches.sort(key=lambda match: match.vector_score, reverse=True)
        return matches[:limit]

    def _ensure_collection(self, *, collection_name: str, dimension: int) -> None:
        if dimension < 1:
            raise RuntimeError("Milvus vector dimension must be greater than 0")
        if self._has_collection(collection_name):
            existing_dimension = self._collection_dimension(collection_name)
            if existing_dimension != dimension:
                raise RuntimeError(
                    "Milvus collection vector dimension mismatch: "
                    f"existing={existing_dimension}, incoming={dimension}. "
                    "Use a separate RAG_MILVUS_COLLECTION or rebuild the local Milvus DB."
                )
            return

        schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field(field_name="id", datatype=DataType.VARCHAR, is_primary=True, max_length=128)
        schema.add_field(field_name=self._VECTOR_FIELD, datatype=DataType.FLOAT_VECTOR, dim=dimension)
        schema.add_field(field_name="knowledge_base_id", datatype=DataType.VARCHAR, max_length=128)
        schema.add_field(field_name="document_id", datatype=DataType.VARCHAR, max_length=128)
        schema.add_field(field_name="title", datatype=DataType.VARCHAR, max_length=512)
        schema.add_field(field_name="text", datatype=DataType.VARCHAR, max_length=8192)
        schema.add_field(field_name="metadata_json", datatype=DataType.VARCHAR, max_length=8192)
        schema.add_field(field_name="tenant_id", datatype=DataType.VARCHAR, max_length=128)
        schema.add_field(field_name="permission_tags_json", datatype=DataType.VARCHAR, max_length=2048)
        schema.add_field(field_name="created_at", datatype=DataType.VARCHAR, max_length=64)

        index_params = self._client.prepare_index_params()
        index_params.add_index(field_name=self._VECTOR_FIELD, index_type="FLAT", metric_type="COSINE")
        self._client.create_collection(
            collection_name=collection_name,
            schema=schema,
            index_params=index_params,
        )

    def _collection_dimension(self, collection_name: str) -> int:
        description = self._client.describe_collection(collection_name=collection_name)
        for field in description.get("fields", []):
            if field.get("name") == self._VECTOR_FIELD:
                return int(field.get("params", {}).get("dim", 0))
        return 0

    def _has_collection(self, collection_name: str) -> bool:
        return self._client.has_collection(collection_name=collection_name)

    def _query_rows(self, collection_name: str, filter_expression: str, *, output_fields: list[str]) -> list[dict]:
        return list(
            self._client.query(
                collection_name=collection_name,
                filter=filter_expression,
                output_fields=output_fields,
            )
        )

    def _chunk_to_row(self, chunk: Chunk) -> dict:
        return {
            "id": chunk.id,
            "knowledge_base_id": chunk.knowledge_base_id,
            "document_id": chunk.document_id,
            "title": self._bounded_text(chunk.title, 512, "chunk title"),
            "text": self._bounded_text(chunk.text, 8192, "chunk text"),
            "metadata_json": self._bounded_text(self._json_dumps(chunk.metadata), 8192, "chunk metadata"),
            "tenant_id": self._bounded_text(chunk.tenant_id, 128, "chunk tenant_id"),
            "permission_tags_json": self._bounded_text(
                self._json_dumps(chunk.permission_tags),
                2048,
                "chunk permission_tags",
            ),
            "embedding": chunk.embedding,
            "created_at": chunk.created_at,
        }

    def _row_to_chunk(self, row: dict) -> Chunk:
        return Chunk(
            id=row["id"],
            knowledge_base_id=row["knowledge_base_id"],
            document_id=row["document_id"],
            title=row["title"],
            text=row["text"],
            metadata=self._json_loads(row.get("metadata_json") or "{}", {}),
            tenant_id=row.get("tenant_id") or "default",
            permission_tags=self._json_loads(row.get("permission_tags_json") or "[]", []),
            embedding=row.get("embedding") or [],
            created_at=row["created_at"],
        )

    def _filter_expression(self, *, kb_id: str, tenant_id: str | None = None) -> str:
        expression = f"knowledge_base_id == {self._literal(kb_id)}"
        if tenant_id is not None:
            expression += f" and tenant_id == {self._literal(tenant_id)}"
        return expression

    def _literal(self, value: str) -> str:
        return json.dumps(value, ensure_ascii=False)

    def _json_dumps(self, value: object) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    def _json_loads(self, value: str, default: object) -> object:
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return default

    def _bounded_text(self, value: str, max_length: int, label: str) -> str:
        if len(value) > max_length:
            raise ValueError(f"{label} is too large for Milvus storage; limit is {max_length} characters")
        return value

    def _is_allowed(self, required_tags: list[str], user_tags: set[str]) -> bool:
        if not required_tags:
            return True
        return set(required_tags).issubset(user_tags)

    def _chunks_by_dimension(self, chunks: list[Chunk]) -> dict[int, list[Chunk]]:
        grouped: dict[int, list[Chunk]] = {}
        for chunk in chunks:
            dimension = len(chunk.embedding)
            if dimension < 1:
                raise RuntimeError(f"chunk '{chunk.id}' has empty embedding")
            grouped.setdefault(dimension, []).append(chunk)
        return grouped

    def _collection_name_for_dimension(self, dimension: int) -> str:
        return f"{self.collection_name}_d{dimension}"

    def _active_collection_names(self) -> list[str]:
        prefix = f"{self.collection_name}_d"
        names = [
            name
            for name in self._client.list_collections()
            if name == self.collection_name or name.startswith(prefix)
        ]
        return sorted(names)

    def _collection_names_for_dimension(self, dimension: int) -> list[str]:
        names: list[str] = []
        dimension_collection = self._collection_name_for_dimension(dimension)
        if self._has_collection(dimension_collection):
            names.append(dimension_collection)
        if self._has_collection(self.collection_name) and self._collection_dimension(self.collection_name) == dimension:
            names.append(self.collection_name)
        return names

    def _flush(self, collection_name: str) -> None:
        if self._has_collection(collection_name):
            self._client.flush(collection_name=collection_name)


def create_chunk_store(*, uri: Path | str, collection_name: str) -> MilvusChunkStore:
    return MilvusChunkStore(uri=uri, collection_name=collection_name)
