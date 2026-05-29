from __future__ import annotations

import math

from rag_demo.embeddings import EmbeddingProvider
from rag_demo.models import AccessContext, Source
from rag_demo.store import JsonStore


class Retriever:
    def __init__(self, store: JsonStore, embeddings: EmbeddingProvider) -> None:
        self.store = store
        self.embeddings = embeddings

    async def retrieve(self, *, kb_id: str, query: str, top_k: int, access: AccessContext) -> list[Source]:
        query_embedding = (await self.embeddings.embed([query]))[0]
        chunks = self.store.list_chunks(
            kb_id=kb_id,
            tenant_id=access.tenant_id,
            permission_tags=access.permission_tags,
        )
        scored = [
            (
                self._score(
                    query=query,
                    query_embedding=query_embedding,
                    text=chunk.text,
                    text_embedding=chunk.embedding,
                ),
                chunk,
            )
            for chunk in chunks
        ]
        scored.sort(key=lambda item: item[0]["score"], reverse=True)

        sources = [
            Source(
                knowledge_base_id=chunk.knowledge_base_id,
                document_id=chunk.document_id,
                chunk_id=chunk.id,
                title=chunk.title,
                score=score["score"],
                vector_score=score["vector_score"],
                lexical_score=score["lexical_score"],
                tenant_id=chunk.tenant_id,
                permission_tags=chunk.permission_tags,
                text=chunk.text,
            )
            for score, chunk in scored[:top_k]
            if score["score"] > 0
        ]
        return self._enforce_boundary(kb_id=kb_id, sources=sources)

    def _enforce_boundary(self, *, kb_id: str, sources: list[Source]) -> list[Source]:
        leaked = [source for source in sources if source.knowledge_base_id != kb_id]
        if leaked:
            leaked_ids = ", ".join(source.chunk_id for source in leaked)
            raise RuntimeError(f"retrieval boundary violation: {leaked_ids}")
        return sources

    def _cosine(self, left: list[float], right: list[float]) -> float:
        if not left or not right or len(left) != len(right):
            return 0.0
        dot = sum(a * b for a, b in zip(left, right))
        left_norm = math.sqrt(sum(a * a for a in left))
        right_norm = math.sqrt(sum(b * b for b in right))
        if left_norm == 0 or right_norm == 0:
            return 0.0
        return dot / (left_norm * right_norm)

    def _score(
        self,
        *,
        query: str,
        query_embedding: list[float],
        text: str,
        text_embedding: list[float],
    ) -> dict[str, float]:
        vector_score = max(0.0, self._cosine(query_embedding, text_embedding))
        lexical_score = self._lexical_overlap(query, text)
        return {
            "score": vector_score + lexical_score,
            "vector_score": vector_score,
            "lexical_score": lexical_score,
        }

    def _lexical_overlap(self, query: str, text: str) -> float:
        query_tokens = self._tokens(query)
        text_tokens = self._tokens(text)
        if not query_tokens or not text_tokens:
            return 0.0
        return len(query_tokens & text_tokens) / len(query_tokens)

    def _tokens(self, text: str) -> set[str]:
        compact = "".join(ch.lower() for ch in text if not ch.isspace())
        char_grams = {compact[index : index + 2] for index in range(max(0, len(compact) - 1))}
        chars = set(compact)
        words = {word.lower() for word in text.replace("\n", " ").split() if word.strip()}
        return chars | char_grams | words
