"""用于短期运行状态的小型 Redis 适配器。

SQLite 是用户、知识库、文档、对话、产物和操作事件的持久化事实来源。
Redis 刻意只保存临时状态：登录会话、JWT 撤销记录，以及未来可能加入的缓存。
保持这个边界清晰，可以避免 Redis 数据丢失时污染业务元数据。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from boundary_rag.config import Settings


class RedisUnavailableError(RuntimeError):
    """当某个操作必须使用 Redis 但连接不可用时抛出。"""
    pass


@dataclass(frozen=True)
class RedisStatus:
    """展示在设置页/运行诊断中的 Redis 健康信息。"""
    enabled: bool
    ready: bool
    url: str
    message: str = ""


class RedisCache:
    """带命名空间 key 和 JSON 辅助方法的惰性异步 Redis 客户端。"""

    def __init__(
        self,
        *,
        enabled: bool,
        url: str,
        key_prefix: str = "boundaryrag",
        timeout_seconds: float = 1.0,
        default_ttl_seconds: int = 3600,
    ) -> None:
        self.enabled = enabled
        self.url = url
        self.key_prefix = key_prefix.strip(":") or "boundaryrag"
        self.timeout_seconds = timeout_seconds
        self.default_ttl_seconds = default_ttl_seconds
        self._client: Any | None = None

    @property
    def safe_url(self) -> str:
        """返回可安全展示在日志或诊断信息中的 Redis URL。"""
        return _sanitize_url(self.url)

    async def close(self) -> None:
        """在应用关闭时释放惰性创建的 Redis 连接。"""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def status(self) -> RedisStatus:
        """探测 Redis 状态，但不让健康检查导致应用崩溃。"""
        if not self.enabled:
            return RedisStatus(enabled=False, ready=False, url=self.safe_url, message="disabled")
        try:
            client = await self._client_or_raise()
            await client.ping()
        except Exception as exc:  # Redis 健康检查应该报告错误，而不是让应用崩溃。
            return RedisStatus(enabled=True, ready=False, url=self.safe_url, message=str(exc))
        return RedisStatus(enabled=True, ready=True, url=self.safe_url, message="ok")

    async def get_json(self, key: str) -> Any | None:
        """从带命名空间的缓存中读取 JSON 值。"""
        if not self.enabled:
            return None
        try:
            client = await self._client_or_raise()
            value = await client.get(self._key("json", key))
        except Exception as exc:
            raise RedisUnavailableError(f"Redis is unavailable: {exc}") from exc
        if not value:
            return None
        return json.loads(value)

    async def set_json(self, key: str, value: Any, *, ttl_seconds: int | None = None) -> None:
        """写入带 TTL 的 JSON 值；登录会话走这个路径。"""
        if not self.enabled:
            return
        ttl = ttl_seconds or self.default_ttl_seconds
        try:
            client = await self._client_or_raise()
            await client.setex(self._key("json", key), ttl, json.dumps(value, ensure_ascii=False))
        except Exception as exc:
            raise RedisUnavailableError(f"Redis is unavailable: {exc}") from exc

    async def delete_json(self, key: str) -> None:
        """删除 JSON 缓存项，通常用于退出登录。"""
        if not self.enabled:
            return
        try:
            client = await self._client_or_raise()
            await client.delete(self._key("json", key))
        except Exception as exc:
            raise RedisUnavailableError(f"Redis is unavailable: {exc}") from exc

    async def revoke_jwt(self, token_id: str, *, ttl_seconds: int) -> None:
        """把 JWT 加入黑名单，直到它自然过期。"""
        if not self.enabled:
            raise RedisUnavailableError("Redis is disabled; set RAG_REDIS_ENABLED=true to revoke JWT tokens")
        ttl = max(1, ttl_seconds)
        try:
            client = await self._client_or_raise()
            await client.setex(self._key("jwt", "revoked", token_id), ttl, "1")
        except Exception as exc:
            raise RedisUnavailableError(f"Redis is unavailable: {exc}") from exc

    async def is_jwt_revoked(self, token_id: str) -> bool:
        """检查某个 JWT 标识是否已在黑名单中。"""
        if not self.enabled:
            return False
        try:
            client = await self._client_or_raise()
            return bool(await client.exists(self._key("jwt", "revoked", token_id)))
        except Exception as exc:
            raise RedisUnavailableError(f"Redis is unavailable: {exc}") from exc

    async def _client_or_raise(self) -> Any:
        """首次使用时再创建 Redis 客户端，保持模块导入轻量。"""
        if self._client is None:
            try:
                import redis.asyncio as redis
            except ImportError as exc:
                raise RedisUnavailableError("redis package is not installed") from exc
            self._client = redis.from_url(
                self.url,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=self.timeout_seconds,
                socket_timeout=self.timeout_seconds,
            )
        return self._client

    def _key(self, *parts: str) -> str:
        """在配置的产品命名空间下构建稳定 key。"""
        safe_parts = [part.strip(":") for part in parts if part.strip(":")]
        return ":".join([self.key_prefix, *safe_parts])


def create_redis_cache(settings: Settings) -> RedisCache:
    """供 FastAPI 依赖注入使用的工厂函数。"""
    return RedisCache(
        enabled=settings.redis_enabled,
        url=settings.redis_url,
        key_prefix=settings.redis_key_prefix,
        timeout_seconds=settings.redis_timeout_seconds,
        default_ttl_seconds=settings.redis_default_ttl_seconds,
    )


def _sanitize_url(url: str) -> str:
    """在向用户展示 Redis URL 前隐藏其中的密码。"""
    parsed = urlsplit(url)
    if not parsed.password:
        return url
    username = parsed.username or ""
    host = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    netloc = f"{username}:***@{host}{port}" if username else f"***@{host}{port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))
