import sys
from types import SimpleNamespace

import pytest

from rag_demo.config import Settings
from rag_demo.embeddings import DashScopeEmbeddingProvider


def test_extract_dashscope_embedding_response() -> None:
    provider = DashScopeEmbeddingProvider(
        Settings(
            embedding_provider="dashscope",
            dashscope_api_key="test-key",
        )
    )

    response = {
        "status_code": 200,
        "output": {
            "embeddings": [
                {"index": 1, "embedding": [0.3, 0.4]},
                {"index": 0, "embedding": [0.1, 0.2]},
            ]
        },
    }

    assert provider._extract_embeddings(response) == [[0.1, 0.2], [0.3, 0.4]]


@pytest.mark.asyncio
async def test_dashscope_embedding_provider_batches_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[dict[str, str]]] = []

    class FakeMultiModalEmbedding:
        @staticmethod
        def call(*, model: str, input: list[dict[str, str]]) -> dict:
            calls.append(input)
            offset = sum(len(call) for call in calls[:-1])
            return {
                "status_code": 200,
                "output": {
                    "embeddings": [
                        {"index": index, "embedding": [float(offset + index)]}
                        for index, _ in enumerate(input)
                    ]
                },
            }

    fake_dashscope = SimpleNamespace(api_key=None, MultiModalEmbedding=FakeMultiModalEmbedding)
    monkeypatch.setitem(sys.modules, "dashscope", fake_dashscope)
    provider = DashScopeEmbeddingProvider(
        Settings(
            embedding_provider="dashscope",
            dashscope_api_key="test-key",
            dashscope_embedding_batch_size=20,
        )
    )

    embeddings = await provider.embed([f"text-{index}" for index in range(45)])

    assert [len(call) for call in calls] == [20, 20, 5]
    assert embeddings == [[float(index)] for index in range(45)]
