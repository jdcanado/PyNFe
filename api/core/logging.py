"""Logging estruturado da API.

- `get_logger` retorna um logger configurado pelo nível de `settings.log_level`.
- `RequestLoggingMiddleware` registra método, path, status, duração, IP e
  api_client_id de cada request HTTP (sem logar o payload — sanitização LGPD).
"""

from __future__ import annotations

import logging
import sys
import time

from jose import jwt
from starlette.middleware.base import BaseHTTPMiddleware

LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"

_logging_configured = False


def configure_logging() -> None:
    """Configura o logging raiz com o nível de `settings.log_level` (lazy)."""
    global _logging_configured
    if _logging_configured:
        return

    from api.core.config import get_settings

    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format=LOG_FORMAT,
        stream=sys.stdout,
        force=True,
    )
    _logging_configured = True


def get_logger(name: str) -> logging.Logger:
    """Retorna um logger da API com a configuração padrão aplicada."""
    configure_logging()
    return logging.getLogger(name)


def _extrair_client_id(request) -> str | None:
    """Extrai o `sub` (api_client_id) do JWT sem validar — apenas para auditoria.

    A validação real é feita pelo `get_current_client`; aqui o objetivo é
    registrar a identidade no log de requisições.
    """
    authorization = request.headers.get("authorization", "")
    if not authorization.startswith("Bearer "):
        return None
    token = authorization.removeprefix("Bearer ").strip()
    try:
        payload = jwt.decode(token, key=None, options={"verify_signature": False})
        return payload.get("sub")
    except Exception:  # noqa: BLE001
        return None


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Registra cada request HTTP (método, path, status, duração, IP e client).

    Não loga o corpo da requisição (sanitização LGPD).
    """

    async def dispatch(self, request, call_next):
        logger = get_logger("api.request")
        inicio = time.monotonic()
        response = await call_next(request)
        duracao_ms = (time.monotonic() - inicio) * 1000
        client_ip = request.client.host if request.client else "-"
        api_client_id = _extrair_client_id(request) or "-"
        logger.info(
            "%s %s -> %s (%.1f ms) ip=%s client=%s",
            request.method,
            request.url.path,
            response.status_code,
            duracao_ms,
            client_ip,
            api_client_id,
        )
        return response
