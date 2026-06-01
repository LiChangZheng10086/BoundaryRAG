from __future__ import annotations

import asyncio
import json
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

import httpx

from rag_demo.config import Settings
from rag_demo.models import ConversationMessage, KnowledgeBase, Source


class LLMProvider(ABC):
    @abstractmethod
    async def answer(
        self,
        *,
        kb: KnowledgeBase,
        instruction: str,
        sources: list[Source],
        history: list[ConversationMessage] | None = None,
    ) -> str:
        raise NotImplementedError

    async def stream_answer(
        self,
        *,
        kb: KnowledgeBase,
        instruction: str,
        sources: list[Source],
        history: list[ConversationMessage] | None = None,
    ) -> AsyncIterator[str]:
        answer = await self.answer(kb=kb, instruction=instruction, sources=sources, history=history)
        for chunk in _text_chunks(answer):
            yield chunk
            await asyncio.sleep(0)


class LocalBoundaryLLMProvider(LLMProvider):
    async def answer(
        self,
        *,
        kb: KnowledgeBase,
        instruction: str,
        sources: list[Source],
        history: list[ConversationMessage] | None = None,
    ) -> str:
        if not sources:
            return f"我在 {kb.name} 中没有找到足够依据，不能使用其他知识库的信息回答。"

        history_text = ""
        if history:
            history_lines = [f"{message.role}: {message.content[:120]}" for message in history[-6:]]
            history_text = "结合本轮对话上下文：\n" + "\n".join(history_lines) + "\n\n"
        snippets = "\n".join(f"- {source.text[:180]}" for source in sources)
        return (
            history_text +
            f"基于 {kb.name} 的资料，可以这样回答：\n"
            f"{snippets}\n\n"
            f"针对你的问题：{instruction}\n"
            "以上内容只使用当前知识库生成。"
        )


class DeepSeekLLMProvider(LLMProvider):
    def __init__(self, settings: Settings) -> None:
        if not settings.deepseek_api_key:
            raise ValueError("DEEPSEEK_API_KEY is required when LLM_PROVIDER=deepseek")
        self.api_key = settings.deepseek_api_key
        self.model = settings.deepseek_model
        self.base_url = settings.deepseek_base_url.rstrip("/")

    def _messages(
        self,
        *,
        kb: KnowledgeBase,
        instruction: str,
        sources: list[Source],
        history: list[ConversationMessage] | None = None,
    ) -> list[dict[str, str]]:
        context = "\n\n".join(
            f"[{index}] title={source.title} chunk_id={source.chunk_id}\n{source.text}"
            for index, source in enumerate(sources, start=1)
        )
        system = (
            "你是一个企业知识库助手。必须严格遵守知识库边界："
            f"当前只能使用 knowledge_base_id={kb.id} 的资料和技能。"
            "如果上下文没有依据，必须说明不知道，不能使用其他知识库、历史经验或臆测补全。"
            "回答需要给出简洁结论，不要展示来源编号、chunk_id、score 或来源列表。"
        )
        user = f"用户需求：{instruction}\n\n当前知识库资料：\n{context or '无可用资料'}"
        messages = [{"role": "system", "content": system}]
        for message in history or []:
            messages.append({"role": message.role, "content": message.content})
        messages.append({"role": "user", "content": user})
        return messages

    async def answer(
        self,
        *,
        kb: KnowledgeBase,
        instruction: str,
        sources: list[Source],
        history: list[ConversationMessage] | None = None,
    ) -> str:
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={
                        "model": self.model,
                        "messages": self._messages(kb=kb, instruction=instruction, sources=sources, history=history),
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

    async def stream_answer(
        self,
        *,
        kb: KnowledgeBase,
        instruction: str,
        sources: list[Source],
        history: list[ConversationMessage] | None = None,
    ) -> AsyncIterator[str]:
        try:
            timeout = httpx.Timeout(120.0, connect=10.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={
                        "model": self.model,
                        "messages": self._messages(kb=kb, instruction=instruction, sources=sources, history=history),
                        "temperature": 0.2,
                        "stream": True,
                    },
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line.removeprefix("data:").strip()
                        if not data or data == "[DONE]":
                            continue
                        payload = json.loads(data)
                        delta = payload["choices"][0].get("delta", {}).get("content") or ""
                        if delta:
                            yield delta
        except httpx.HTTPError as exc:
            raise RuntimeError(f"DeepSeek stream request failed: {exc}") from exc
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError("DeepSeek stream response format is invalid") from exc


def create_llm_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "deepseek":
        return DeepSeekLLMProvider(settings)
    return LocalBoundaryLLMProvider()


def _text_chunks(text: str, size: int = 16) -> list[str]:
    return [text[index : index + size] for index in range(0, len(text), size)] or [""]
