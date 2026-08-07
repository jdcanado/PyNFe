"""Dependências FastAPI: DB, Redis e autenticação."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from uuid import UUID

import redis.asyncio as redis_async
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import get_settings
from api.core.database import get_db
from api.core.security import decode_jwt_token
from api.models import APIClient
from api.utils.noop_redis import NoopRedis

settings = get_settings()

_redis_client: redis_async.Redis | NoopRedis | None = None


def get_redis() -> redis_async.Redis | NoopRedis:
    """Retorna o cliente Redis (Upstash) singleton.

    Quando KV_URL não está configurado, retorna um NoopRedis que simula
    cache-miss em todas as operações, permitindo que a API funcione sem Redis.
    """
    global _redis_client
    if _redis_client is not None:
        return _redis_client

    kv_url = settings.kv_url
    if not kv_url or not kv_url.startswith(("redis://", "rediss://", "unix://")):
        _redis_client = NoopRedis()
        return _redis_client

    _redis_client = redis_async.from_url(
        kv_url,
        password=settings.kv_token,
        decode_responses=True,
    )
    return _redis_client


async def get_current_client(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIClient:
    """Extrai o JWT do header Authorization e busca o APIClient no banco."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header",
        )

    token = authorization.removeprefix("Bearer ").strip()
    try:
        payload = decode_jwt_token(token)
    except Exception as exc:  # JWTError
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        ) from exc

    client_id = payload.get("sub")
    if not client_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing subject",
        )

    try:
        client_id_uuid = UUID(client_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing subject",
        ) from None

    client = await db.get(APIClient, client_id_uuid)
    if client is None or not client.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Client not found or inactive",
        )
    return client


async def get_redis_dep() -> AsyncGenerator[redis_async.Redis | NoopRedis, None]:
    """Dependency que fornece o cliente Redis (para uso como Depends)."""
    yield get_redis()
