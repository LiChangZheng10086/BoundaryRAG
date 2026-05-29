from __future__ import annotations

from abc import ABC, abstractmethod

import httpx

from rag_demo.config import Settings
from rag_demo.models import KnowledgeBase, Source


class LLMProvider(ABC):
    @abstractmethod
    async def answer(self, *, kb: KnowledgeBase, instruction: str, sources: list[Source]) -> str:
        raise NotImplementedError


class LocalBoundaryLLMProvider(LLMProvider):
    async def answer(self, *, kb: KnowledgeBase, instruction: str, sources: list[Source]) -> str:
        if not sources:
            return f"我在 {kb.name} 中没有找到足够依据，不能使用其他知识库的信息回答。"

        snippets = "\n".join(f"- {source.title}: {source.text[:180]}" for source in sources)
        return (
            f"基于 {kb.name} 的资料，我找到以下依据：\n"
            f"{snippets}\n\n"
            f"针对你的需求：{instruction}\n"
            "以上回答只使用当前知识库的内容。"
        )


class DeepSeekLLMProvider(LLMProvider):
    def __init__(self, settings: Settings) -> None:
        if not settings.deepseek_api_key:
            raise ValueError("DEEPSEEK_API_KEY is required when LLM_PROVIDER=deepseek")
        self.api_key = settings.deepseek_api_key
        self.model = settings.deepseek_model
        self.base_url = settings.deepseek_base_url.rstrip("/")

    async def answer(self, *, kb: KnowledgeBase, instruction: str, sources: list[Source]) -> str:
        context = "\n\n".join(
            f"[{index}] title={source.title} chunk_id={source.chunk_id}\n{source.text}"
            for index, source in enumerate(sources, start=1)
        )
        system = (
            "你是一个企业知识库助手。必须严格遵守知识库边界："
            f"当前只能使用 knowledge_base_id={kb.id} 的资料和技能。"
            "如果上下文没有依据，必须说明不知道，不能使用其他知识库、历史经验或臆测补全。"
            "回答需要给出简洁结论，并尽量引用来源编号。"
        )
        user = f"用户需求：{instruction}\n\n当前知识库资料：\n{context or '无可用资料'}"

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        "temperature": 0.2,
                    },
                )
                response.raise_for_status()
                data = response.json()
                return data["choices"][0]["message"]["content"]
        except httpx.HTTPError as exc:
            raise RuntimeError(f"DeepSeek request failed: {exc}") from exc
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise RuntimeError("DeepSeek response format is invalid") from exc


def create_llm_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "deepseek":
        return DeepSeekLLMProvider(settings)
    return LocalBoundaryLLMProvider()
