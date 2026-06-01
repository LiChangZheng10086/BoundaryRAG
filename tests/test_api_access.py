from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from rag_demo.app import app, get_redis_cache, get_service
from rag_demo.auth import sign_access_token
from rag_demo.config import Settings
from rag_demo.embeddings import LocalHashEmbeddingProvider
from rag_demo.llm import LocalBoundaryLLMProvider
from rag_demo.models import AccessContext
from rag_demo.service import RagService
from rag_demo.store import JsonStore, SqliteStore


def make_service(tmp_path: Path) -> RagService:
    return RagService(
        store=JsonStore(tmp_path),
        embeddings=LocalHashEmbeddingProvider(),
        llm=LocalBoundaryLLMProvider(),
        artifact_dir=tmp_path / "artifacts",
    )


class FakeRedisCache:
    enabled = True
    safe_url = "redis://fake/0"

    def __init__(self) -> None:
        self.revoked: set[str] = set()

    async def status(self):
        return SimpleNamespace(enabled=True, ready=True, url=self.safe_url, message="ok")

    async def revoke_jwt(self, token_id: str, *, ttl_seconds: int) -> None:
        assert ttl_seconds > 0
        self.revoked.add(token_id)

    async def is_jwt_revoked(self, token_id: str) -> bool:
        return token_id in self.revoked


def test_api_uses_headers_not_body_for_permissions(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    app.dependency_overrides[get_service] = lambda: service
    try:
        client = TestClient(app)
        headers = {"X-Tenant-Id": "default", "X-Permission-Tags": "salary"}
        response = client.post(
            "/knowledge-bases",
            headers=headers,
            json={
                "id": "kb_api",
                "name": "API 权限库",
                "tenant_id": "default",
                "allowed_skills": ["answer_question"],
            },
        )
        assert response.status_code == 200

        response = client.post(
            "/knowledge-bases/kb_api/documents",
            headers=headers,
            json={
                "title": "薪酬制度",
                "content": "薪酬制度：年终奖按照绩效等级计算。",
                "permission_tags": ["salary"],
            },
        )
        assert response.status_code == 200

        forged = client.post(
            "/knowledge-bases/kb_api/query",
            headers={"X-Tenant-Id": "default"},
            json={
                "question": "年终奖怎么算？",
                "top_k": 5,
                "access": {"tenant_id": "default", "permission_tags": ["salary"]},
            },
        )
        assert forged.status_code == 422

        allowed = client.post(
            "/knowledge-bases/kb_api/query",
            headers=headers,
            json={"question": "年终奖怎么算？", "top_k": 5},
        )
        assert allowed.status_code == 200
        assert allowed.json()["sources"]

        denied_preview = client.get(
            "/knowledge-bases/kb_api/documents/" + allowed.json()["sources"][0]["document_id"],
            headers={"X-Tenant-Id": "default"},
        )
        assert denied_preview.status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_query_stream_returns_plain_answer_text(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    app.dependency_overrides[get_service] = lambda: service
    try:
        client = TestClient(app)
        response = client.post(
            "/knowledge-bases",
            json={
                "id": "kb_stream",
                "name": "流式问答库",
                "tenant_id": "default",
                "allowed_skills": ["answer_question"],
            },
        )
        assert response.status_code == 200

        response = client.post(
            "/knowledge-bases/kb_stream/documents",
            json={
                "title": "流式资料",
                "content": "Alpha 是流式回答测试内容。",
            },
        )
        assert response.status_code == 200

        with client.stream(
            "POST",
            "/knowledge-bases/kb_stream/query/stream",
            json={"question": "Alpha 是什么？", "top_k": 5},
        ) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/plain")
            conversation_id = response.headers["x-conversation-id"]
            answer = "".join(response.iter_text())

        assert "Alpha" in answer
        assert '"sources"' not in answer
        messages = service.store.list_conversation_messages(conversation_id=conversation_id)
        assert [message.role for message in messages] == ["user", "assistant"]

        history = client.get("/knowledge-bases/kb_stream/conversations")
        assert history.status_code == 200
        assert history.json()[0]["id"] == conversation_id

        visible_messages = client.get(f"/knowledge-bases/kb_stream/conversations/{conversation_id}/messages")
        assert visible_messages.status_code == 200
        assert [message["role"] for message in visible_messages.json()] == ["user", "assistant"]

        with client.stream(
            "POST",
            "/knowledge-bases/kb_stream/query/stream",
            json={"question": "结合上文继续解释 Alpha", "top_k": 5, "conversation_id": conversation_id},
        ) as response:
            assert response.status_code == 200
            assert response.headers["x-conversation-id"] == conversation_id
            follow_up = "".join(response.iter_text())

        assert "结合本轮对话上下文" in follow_up
        messages = service.store.list_conversation_messages(conversation_id=conversation_id)
        assert [message.role for message in messages] == ["user", "assistant", "user", "assistant"]
    finally:
        app.dependency_overrides.clear()


def test_jwt_auth_mode_requires_and_validates_bearer_token(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RAG_AUTH_MODE", "jwt")
    monkeypatch.setenv("RAG_JWT_SECRET", "test-secret")

    service = make_service(tmp_path)
    app.dependency_overrides[get_service] = lambda: service
    try:
        client = TestClient(app)

        missing = client.get("/knowledge-bases")
        assert missing.status_code == 401

        settings = Settings(auth_mode="jwt", jwt_secret="test-secret")
        token = sign_access_token(
            AccessContext(user_id="alice", tenant_id="tenant-a", permission_tags=["hr"]),
            settings,
        )
        headers = {"Authorization": f"Bearer {token}"}
        response = client.post(
            "/knowledge-bases",
            headers=headers,
            json={
                "id": "kb_jwt",
                "name": "JWT 权限库",
                "tenant_id": "tenant-a",
                "permission_tags": ["hr"],
            },
        )
        assert response.status_code == 200
        assert response.json()["tenant_id"] == "tenant-a"

        bad_token = sign_access_token(
            AccessContext(user_id="mallory", tenant_id="tenant-a", permission_tags=["hr"]),
            Settings(auth_mode="jwt", jwt_secret="wrong-secret"),
        )
        rejected = client.get("/knowledge-bases", headers={"Authorization": f"Bearer {bad_token}"})
        assert rejected.status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_jwt_logout_revokes_token_in_redis_blacklist(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RAG_AUTH_MODE", "jwt")
    monkeypatch.setenv("RAG_JWT_SECRET", "test-secret")

    service = make_service(tmp_path)
    cache = FakeRedisCache()
    app.dependency_overrides[get_service] = lambda: service
    app.dependency_overrides[get_redis_cache] = lambda: cache
    try:
        client = TestClient(app)
        settings = Settings(auth_mode="jwt", jwt_secret="test-secret")
        token = sign_access_token(
            AccessContext(user_id="alice", tenant_id="tenant-a", permission_tags=["hr"]),
            settings,
            expires_in_seconds=3600,
        )
        headers = {"Authorization": f"Bearer {token}"}

        response = client.post("/auth/logout", headers=headers)
        assert response.status_code == 200
        payload = response.json()
        assert payload["revoked"] is True
        assert payload["token_id"]

        rejected = client.get("/knowledge-bases", headers=headers)
        assert rejected.status_code == 401
        assert "revoked" in rejected.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_operation_events_are_scoped_to_user(tmp_path: Path) -> None:
    service = RagService(
        store=SqliteStore(tmp_path / "boundaryrag.sqlite3"),
        embeddings=LocalHashEmbeddingProvider(),
        llm=LocalBoundaryLLMProvider(),
        artifact_dir=tmp_path / "artifacts",
    )
    app.dependency_overrides[get_service] = lambda: service
    try:
        client = TestClient(app)
        alice_headers = {"X-User-Id": "alice", "X-Tenant-Id": "tenant-a"}
        bob_headers = {"X-User-Id": "bob", "X-Tenant-Id": "tenant-a"}

        response = client.post(
            "/knowledge-bases",
            headers=alice_headers,
            json={
                "id": "kb_ops",
                "name": "操作记录库",
                "tenant_id": "tenant-a",
                "allowed_skills": ["answer_question"],
            },
        )
        assert response.status_code == 200

        response = client.post(
            "/knowledge-bases/kb_ops/documents",
            headers=alice_headers,
            json={
                "title": "记录文档",
                "content": "这是一条会生成操作记录的文档。",
            },
        )
        assert response.status_code == 200

        alice_events = client.get("/operation-events?limit=20", headers=alice_headers)
        assert alice_events.status_code == 200
        assert alice_events.json()
        assert all(event["user_id"] == "alice" for event in alice_events.json())

        bob_events = client.get("/operation-events?limit=20", headers=bob_headers)
        assert bob_events.status_code == 200
        assert bob_events.json() == []
    finally:
        app.dependency_overrides.clear()
