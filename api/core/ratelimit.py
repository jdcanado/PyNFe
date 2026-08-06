"""Rate limiting por API key com Vercel KV (Upstash Redis) e sliding window.

Limites por plano (minuto/dia):
- free:      30/min   +  1.000/dia
- pro:      300/min   + 10.000/dia
- enterprise: 3.000/min + 100.000/dia

O algoritmo usa um ZSET por janela (minuto e dia): timestamps dos requests
são inseridos com score = epoch; entradas fora da janela são removidas e o
ZCARD dá a contagem atual (janela deslizante). O middleware responde 429 com
headers X-RateLimit-* quando o limite é excedido.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from fastapi import Request
from fastapi.responses import JSONResponse
from jose.exceptions import JWTError
from starlette.middleware.base import BaseHTTPMiddleware

MINUTE_WINDOW = 60  # segundos
DAY_WINDOW = 86_400  # segundos

PLAN_LIMITS: dict[str, dict[str, int]] = {
    "free": {"per_minute": 30, "per_day": 1_000},
    "pro": {"per_minute": 300, "per_day": 10_000},
    "enterprise": {"per_minute": 3_000, "per_day": 100_000},
}

DEFAULT_PLAN = "free"

RATE_LIMIT_HEADERS = ("X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset")


def get_plan_limits(plan: str) -> dict[str, int]:
    """Retorna os limites do plano; planos desconhecidos caem em 'free'."""
    return PLAN_LIMITS.get(plan, PLAN_LIMITS[DEFAULT_PLAN])


@dataclass
class RateLimitResult:
    """Resultado da checagem de rate limit para uma janela."""

    allowed: bool
    limit: int
    remaining: int
    reset_after: int  # segundos até a janela reiniciar


def _redis_keys(client_id: str) -> tuple[str, str]:
    """Chaves Redis das janelas de minuto e dia para o client."""
    return f"ratelimit:{client_id}:minute", f"ratelimit:{client_id}:day"


async def check_and_increment(
    redis: Any,
    client_id: str,
    plan: str,
    *,
    now: float | None = None,
) -> RateLimitResult:
    """Registra o request e retorna se o client ainda pode prosseguir.

    Usa sliding window por ZSET. `now` é injetável para testes.
    """
    limits = get_plan_limits(plan)
    now = now if now is not None else time.time()

    key_minute, key_day = _redis_keys(client_id)
    remaining = limits["per_minute"]

    for key, window, limit in (
        (key_minute, MINUTE_WINDOW, limits["per_minute"]),
        (key_day, DAY_WINDOW, limits["per_day"]),
    ):
        pipe = redis.pipeline()
        pipe.zremrangebyscore(key, 0, now - window)
        pipe.zadd(key, {f"{now:.6f}:{uuid4().hex}": now})
        pipe.zcard(key)
        pipe.expire(key, window * 2)
        count = (await pipe.execute())[2]

        if count > limit:
            return RateLimitResult(
                allowed=False,
                limit=limit,
                remaining=0,
                reset_after=int(window),
            )
        if key == key_minute:
            remaining = max(0, limit - count)

    return RateLimitResult(
        allowed=True,
        limit=limits["per_minute"],
        remaining=remaining,
        reset_after=MINUTE_WINDOW,
    )


def extract_client_id(authorization: str | None) -> str | None:
    """Extrai o subject (id do APIClient) de um JWT Bearer, ou None.

    Import lazy de `decode_jwt_token` para permitir testes sem settings reais.
    """
    if not authorization or not authorization.startswith("Bearer "):
        return None

    from api.core.security import decode_jwt_token

    try:
        payload = decode_jwt_token(authorization[7:])
    except (JWTError, ValueError):
        return None
    return payload.get("sub")


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Middleware HTTP que aplica rate limit por client autenticado."""

    async def dispatch(self, request: Request, call_next):
        from api.core.config import get_settings
        from api.core.database import SessionFactory
        from api.core.dependencies import get_redis
        from api.models import APIClient

        settings = get_settings()
        if not settings.ratelimit_enabled:
            return await call_next(request)

        client_id = extract_client_id(request.headers.get("authorization"))
        if client_id is None:
            return await call_next(request)

        # Resolve o plano do client (default free se não encontrado).
        plan = DEFAULT_PLAN
        async with SessionFactory() as session:
            client = await session.get(APIClient, UUID(client_id))
            if client is not None:
                plan = client.plano

        result = await check_and_increment(get_redis(), client_id, plan)
        headers = {
            "X-RateLimit-Limit": str(result.limit),
            "X-RateLimit-Remaining": str(result.remaining),
            "X-RateLimit-Reset": str(int(time.time()) + result.reset_after),
        }

        if not result.allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "error": "rate_limit_exceeded",
                    "detail": "Limite de requisições excedido. Tente novamente mais tarde.",
                },
                headers=headers,
            )

        response = await call_next(request)
        for header, value in headers.items():
            response.headers[header] = value
        return response
