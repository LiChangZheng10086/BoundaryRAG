from pathlib import Path

from fastapi.testclient import TestClient

from rag_demo.app import app, get_service
from rag_demo.auth import sign_access_token
from rag_demo.config import Settings
from rag_demo.embeddings import LocalHashEmbeddingProvider
from rag_demo.llm import LocalBoundaryLLMProvider
from rag_demo.models import AccessContext
from rag_demo.service import RagService
from rag_demo.store import JsonStore


def make_service(tmp_path: Path) -> RagService:
    return RagService(
        store=JsonStore(tmp_path),
        embeddings=LocalHashEmbeddingProvider(),
        llm=LocalBoundaryLLMProvider(),
        artifact_dir=tmp_path / "artifacts",
    )


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
