"""索引和检索使用的 Embedding provider。

生产路径可以调用 DashScope 多模态 embedding API。没有配置外部 API key 时，
本地 hash embedding provider 可用于演示、离线测试和开发。两者暴露相同的
异步接口，因此 RAG 管线的其他部分不需要关心向量来自哪里。
"""

from __future__ import annotations

import asyncio
import hashlib
import math
from abc import ABC, abstractmethod
from typing import Any

from boundary_rag.config import Settings


class EmbeddingProvider(ABC):
    """把文本 chunk 或用户问题转换成向量的异步接口。"""

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError


class LocalHashEmbeddingProvider(EmbeddingProvider):
    """本地开发使用的确定性兜底 embedding provider。

    它不是语义模型；它生成归一化后的 hash token 向量，让测试可以在不发起
    网络调用的情况下覆盖完整 Milvus/RAG 管线。
    """

    def __init__(self, dimension: int = 384) -> None:
        self.dimension = dimension

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        """把单词、字符和 bigram 投影到固定长度向量中。"""
        vector = [0.0] * self.dimension
        tokens = self._tokenize(text)
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimension
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign

        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return vector
        return [value / norm for value in vector]

    def _tokenize(self, text: str) -> list[str]:
        """混合词级和字符级特征，以同时兼容中文和英文。"""
        compact = "".join(ch.lower() for ch in text if not ch.isspace())
        words = [word.lower() for word in text.replace("\n", " ").split() if word.strip()]
        chars = list(compact)
        char_grams = [compact[index : index + 2] for index in range(max(0, len(compact) - 1))]
        return words + chars + char_grams


class DashScopeEmbeddingProvider(EmbeddingProvider):
    """支持可配置批量大小的 DashScope embedding 适配器。"""

    def __init__(self, settings: Settings) -> None:
        if not settings.dashscope_api_key:
            raise ValueError("DASHSCOPE_API_KEY is required when EMBEDDING_PROVIDER=dashscope")
        if settings.dashscope_embedding_batch_size < 1:
            raise ValueError("DASHSCOPE_EMBEDDING_BATCH_SIZE must be greater than 0")
        self.api_key = settings.dashscope_api_key
        self.model = settings.dashscope_embedding_model
        self.batch_size = settings.dashscope_embedding_batch_size

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """把同步 DashScope SDK 调用放到工作线程中执行。"""
        if not texts:
            return []
        return await asyncio.to_thread(self._embed_sync, texts)

    def _embed_sync(self, texts: list[str]) -> list[list[float]]:
        """按批次请求，避免超过 provider 侧输入数量限制。"""
        embeddings: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            embeddings.extend(self._embed_batch_sync(batch))
        return embeddings

    def _embed_batch_sync(self, texts: list[str]) -> list[list[float]]:
        """对一个安全大小的批次调用 DashScope MultiModalEmbedding。"""
        import dashscope

        dashscope.api_key = self.api_key
        try:
            response = dashscope.MultiModalEmbedding.call(
                model=self.model,
                input=[{"text": text} for text in texts],
            )
        except Exception as exc:
            raise RuntimeError(f"DashScope embedding request failed: {exc}") from exc
        return self._extract_embeddings(response)

    def _extract_embeddings(self, response: Any) -> list[list[float]]:
        """把支持的 DashScope 响应格式统一转换为向量列表。"""
        status_code = self._get(response, "status_code")
        if status_code and status_code != 200:
            code = self._get(response, "code") or "unknown_error"
            message = self._get(response, "message") or "DashScope embedding request failed"
            raise RuntimeError(f"{code}: {message}")

        output = self._get(response, "output") or {}
        embeddings = self._get(output, "embeddings") or self._get(output, "embedding")
        if not embeddings:
            raise RuntimeError("DashScope embedding response does not contain embeddings")

        if isinstance(embeddings, list) and embeddings and isinstance(embeddings[0], dict):
            sorted_items = sorted(embeddings, key=lambda item: item.get("index", 0))
            return [item["embedding"] for item in sorted_items]
        if isinstance(embeddings, list) and embeddings and isinstance(embeddings[0], list):
            return embeddings
        raise RuntimeError("Unsupported DashScope embedding response format")

    def _get(self, value: Any, key: str) -> Any:
        if isinstance(value, dict):
            return value.get(key)
        return getattr(value, key, None)


def create_embedding_provider(settings: Settings) -> EmbeddingProvider:
    """根据环境配置选择 embedding provider。"""
    if settings.embedding_provider == "dashscope":
        return DashScopeEmbeddingProvider(settings)
    return LocalHashEmbeddingProvider()
