from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from uuid import uuid4
from typing import Any

from rag_demo.config import Settings
from rag_demo.models import AccessContext


class AuthError(ValueError):
    pass


class AuthConfigError(RuntimeError):
    pass


def decode_access_token(token: str, settings: Settings) -> AccessContext:
    return access_from_claims(decode_access_token_payload(token, settings))


def decode_access_token_payload(token: str, settings: Settings) -> dict[str, Any]:
    if not settings.jwt_secret:
        raise AuthConfigError("RAG_JWT_SECRET is required when JWT authentication is used")

    header_segment, payload_segment, signature_segment = _split_token(token)
    header = _decode_json(header_segment)
    payload = _decode_json(payload_segment)

    if header.get("alg") != "HS256":
        raise AuthError("only HS256 JWT tokens are supported")

    signed = f"{header_segment}.{payload_segment}".encode("ascii")
    expected_signature = _sign(signed, settings.jwt_secret)
    actual_signature = _b64_decode(signature_segment)
    if not hmac.compare_digest(actual_signature, expected_signature):
        raise AuthError("JWT signature is invalid")

    _validate_registered_claims(payload, settings=settings)
    return payload


def sign_access_token(
    access: AccessContext,
    settings: Settings,
    *,
    expires_in_seconds: int = 3600,
    issued_at: int | None = None,
) -> str:
    if not settings.jwt_secret:
        raise AuthConfigError("RAG_JWT_SECRET is required to sign JWT tokens")

    now = int(time.time()) if issued_at is None else issued_at
    payload: dict[str, Any] = {
        "jti": f"jwt_{uuid4().hex}",
        "sub": access.user_id,
        "tenant_id": access.tenant_id,
        "permission_tags": access.permission_tags,
        "iat": now,
        "exp": now + expires_in_seconds,
    }
    if settings.jwt_issuer:
        payload["iss"] = settings.jwt_issuer
    if settings.jwt_audience:
        payload["aud"] = settings.jwt_audience

    header_segment = _b64_encode_json({"alg": "HS256", "typ": "JWT"})
    payload_segment = _b64_encode_json(payload)
    signed = f"{header_segment}.{payload_segment}".encode("ascii")
    signature_segment = _b64_encode(_sign(signed, settings.jwt_secret))
    return f"{header_segment}.{payload_segment}.{signature_segment}"


def token_cache_id(token: str, payload: dict[str, Any]) -> str:
    jti = payload.get("jti")
    if isinstance(jti, str) and jti.strip():
        return jti
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def token_expires_in_seconds(payload: dict[str, Any], *, now: int | None = None) -> int:
    current = int(time.time()) if now is None else now
    exp = payload.get("exp")
    if not isinstance(exp, int | float):
        raise AuthError("JWT exp claim is required")
    ttl = int(exp) - current
    return ttl if ttl > 0 else 0


def access_from_claims(payload: dict[str, Any]) -> AccessContext:
    return _access_from_claims(payload)


def _split_token(token: str) -> tuple[str, str, str]:
    parts = token.split(".")
    if len(parts) != 3 or not all(parts):
        raise AuthError("JWT must have header, payload, and signature")
    return parts[0], parts[1], parts[2]


def _decode_json(segment: str) -> dict[str, Any]:
    try:
        value = json.loads(_b64_decode(segment))
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
        raise AuthError("JWT contains invalid JSON") from exc
    if not isinstance(value, dict):
        raise AuthError("JWT segment must decode to an object")
    return value


def _validate_registered_claims(payload: dict[str, Any], *, settings: Settings) -> None:
    now = int(time.time())
    leeway = settings.jwt_leeway_seconds

    exp = payload.get("exp")
    if not isinstance(exp, int | float):
        raise AuthError("JWT exp claim is required")
    if exp < now - leeway:
        raise AuthError("JWT has expired")

    nbf = payload.get("nbf")
    if nbf is not None:
        if not isinstance(nbf, int | float):
            raise AuthError("JWT nbf claim must be numeric")
        if nbf > now + leeway:
            raise AuthError("JWT is not valid yet")

    iat = payload.get("iat")
    if iat is not None:
        if not isinstance(iat, int | float):
            raise AuthError("JWT iat claim must be numeric")
        if iat > now + leeway:
            raise AuthError("JWT was issued in the future")

    if settings.jwt_issuer and payload.get("iss") != settings.jwt_issuer:
        raise AuthError("JWT issuer is invalid")

    if settings.jwt_audience:
        audience = payload.get("aud")
        if isinstance(audience, str):
            valid_audience = audience == settings.jwt_audience
        elif isinstance(audience, list):
            valid_audience = settings.jwt_audience in audience
        else:
            valid_audience = False
        if not valid_audience:
            raise AuthError("JWT audience is invalid")


def _access_from_claims(payload: dict[str, Any]) -> AccessContext:
    user_id = payload.get("user_id") or payload.get("sub")
    tenant_id = payload.get("tenant_id")
    permission_tags = payload.get("permission_tags", [])

    if not isinstance(user_id, str) or not user_id.strip():
        raise AuthError("JWT subject is required")
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise AuthError("JWT tenant_id claim is required")

    if isinstance(permission_tags, str):
        tags = [tag.strip() for tag in permission_tags.split(",") if tag.strip()]
    elif isinstance(permission_tags, list) and all(isinstance(tag, str) for tag in permission_tags):
        tags = permission_tags
    else:
        raise AuthError("JWT permission_tags claim must be a string list")

    return AccessContext(user_id=user_id, tenant_id=tenant_id, permission_tags=tags)


def _sign(data: bytes, secret: str) -> bytes:
    return hmac.new(secret.encode("utf-8"), data, hashlib.sha256).digest()


def _b64_encode_json(value: dict[str, Any]) -> str:
    data = json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return _b64_encode(data)


def _b64_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode((value + padding).encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise AuthError("JWT contains invalid base64url") from exc
