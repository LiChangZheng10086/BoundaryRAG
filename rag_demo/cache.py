from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from rag_demo.config import Settings


class RedisUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class RedisStatus:
    enabled: bool
    ready: bool
    url: str
    message: str = ""


class RedisCache:
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
        return _sanitize_url(self.url)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def status(self) -> RedisStatus:
        if not self.enabled:
            return RedisStatus(enabled=False, ready=False, url=self.safe_url, message="disabled")
        try:
            client = await self._client_or_raise()
            await client.ping()
        except Exception as exc:  # Redis health should report errors, not crash the app.
            return RedisStatus(enabled=True, ready=False, url=self.safe_url, message=str(exc))
        return RedisStatus(enabled=True, ready=True, url=self.safe_url, message="ok")

    async def get_json(self, key: str) -> Any | None:
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
        if not self.enabled:
            return
        ttl = ttl_seconds or self.default_ttl_seconds
        try:
            client = await self._client_or_raise()
            await client.setex(self._key("json", key), ttl, json.dumps(value, ensure_ascii=False))
        except Exception as exc:
            raise RedisUnavailableError(f"Redis is unavailable: {exc}") from exc

    async def delete_json(self, key: str) -> None:
        if not self.enabled:
            return
        try:
            client = await self._client_or_raise()
            await client.delete(self._key("json", key))
        except Exception as exc:
            raise RedisUnavailableError(f"Redis is unavailable: {exc}") from exc

    async def revoke_jwt(self, token_id: str, *, ttl_seconds: int) -> None:
        if not self.enabled:
            raise RedisUnavailableError("Redis is disabled; set RAG_REDIS_ENABLED=true to revoke JWT tokens")
        ttl = max(1, ttl_seconds)
        try:
            client = await self._client_or_raise()
            await client.setex(self._key("jwt", "revoked", token_id), ttl, "1")
        except Exception as exc:
            raise RedisUnavailableError(f"Redis is unavailable: {exc}") from exc

    async def is_jwt_revoked(self, token_id: str) -> bool:
        if not self.enabled:
            return False
        try:
            client = await self._client_or_raise()
            return bool(await client.exists(self._key("jwt", "revoked", token_id)))
        except Exception as exc:
            raise RedisUnavailableError(f"Redis is unavailable: {exc}") from exc

    async def _client_or_raise(self) -> Any:
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
        safe_parts = [part.strip(":") for part in parts if part.strip(":")]
        return ":".join([self.key_prefix, *safe_parts])


def create_redis_cache(settings: Settings) -> RedisCache:
    return RedisCache(
        enabled=settings.redis_enabled,
        url=settings.redis_url,
        key_prefix=settings.redis_key_prefix,
        timeout_seconds=settings.redis_timeout_seconds,
        default_ttl_seconds=settings.redis_default_ttl_seconds,
    )


def _sanitize_url(url: str) -> str:
    parsed = urlsplit(url)
    if not parsed.password:
        return url
    username = parsed.username or ""
    host = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    netloc = f"{username}:***@{host}{port}" if username else f"***@{host}{port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))
