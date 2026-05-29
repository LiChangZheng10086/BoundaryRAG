from __future__ import annotations

from rag_demo.embeddings import EmbeddingProvider
from rag_demo.models import AccessContext, Source
from rag_demo.vector_store import ChunkStore


class Retriever:
    def __init__(self, chunk_store: ChunkStore, embeddings: EmbeddingProvider) -> None:
        self.chunk_store = chunk_store
        self.embeddings = embeddings

    async def retrieve(self, *, kb_id: str, query: str, top_k: int, access: AccessContext) -> list[Source]:
        query_embedding = (await self.embeddings.embed([query]))[0]
        matches = self.chunk_store.search_chunks(
            kb_id=kb_id,
            tenant_id=access.tenant_id,
            query_embedding=query_embedding,
            limit=max(top_k * 20, 100),
        )
        scored = [
            (
                self._score(
                    query=query,
                    vector_score=match.vector_score,
                    text=match.chunk.text,
                ),
                match.chunk,
            )
            for match in matches
            if self._is_allowed(match.chunk.permission_tags, set(access.permission_tags))
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

    def _score(
        self,
        *,
        query: str,
        vector_score: float,
        text: str,
    ) -> dict[str, float]:
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

    def _is_allowed(self, required_tags: list[str], user_tags: set[str]) -> bool:
        if not required_tags:
            return True
        return set(required_tags).issubset(user_tags)
